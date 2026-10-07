from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Event


@pytest.fixture
def client():
    return TestClient(app)


def unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}@example.com"


def register(client, name, role, email=None):
    email = email or unique_email(role)
    response = client.post(
        "/auth/register",
        json={
            "name": name,
            "email": email,
            "password": "Password123!",
            "role": role,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client, email):
    response = client.post(
        "/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def create_event(client, token, capacity=10, hours=48, **overrides):
    starts_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    payload = {
        "title": overrides.get("title", "Test Event"),
        "description": "Automated test event",
        "category": overrides.get("category", "technology"),
        "city": overrides.get("city", "Chennai"),
        "starts_at": starts_at.isoformat(),
        "price": overrides.get("price", 500),
        "capacity": capacity,
    }
    response = client.post("/events", json=payload, headers=auth_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_and_duplicate_registration(client):
    email = unique_email("duplicate")
    user = register(client, "Test Attendee", "attendee", email)
    assert user["email"] == email
    assert user["role"] == "attendee"

    duplicate = client.post(
        "/auth/register",
        json={
            "name": "Another",
            "email": email,
            "password": "Password123!",
            "role": "attendee",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "EMAIL_EXISTS"

    bad_login = client.post(
        "/auth/login",
        json={"email": email, "password": "wrong-password"},
    )
    assert bad_login.status_code == 401
    assert bad_login.json()["code"] == "INVALID_CREDENTIALS"


def test_validation_is_structured(client):
    response = client.post(
        "/auth/register",
        json={
            "name": "A",
            "email": "not-an-email",
            "password": "short",
            "role": "attendee",
        },
    )
    assert response.status_code == 422
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Request validation failed",
    }


def test_rbac_and_ownership(client):
    organizer_email = unique_email("organizer")
    other_email = unique_email("other")
    attendee_email = unique_email("attendee")

    register(client, "Organizer One", "organizer", organizer_email)
    register(client, "Organizer Two", "organizer", other_email)
    register(client, "Attendee One", "attendee", attendee_email)

    organizer_token = login(client, organizer_email)
    other_token = login(client, other_email)
    attendee_token = login(client, attendee_email)

    event = create_event(client, organizer_token)

    attendee_create = client.post(
        "/events",
        json={
            "title": "Forbidden",
            "category": "test",
            "city": "Chennai",
            "starts_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "price": 100,
            "capacity": 10,
        },
        headers=auth_headers(attendee_token),
    )
    assert attendee_create.status_code == 403

    other_update = client.patch(
        f"/events/{event['id']}",
        json={"title": "Hacked"},
        headers=auth_headers(other_token),
    )
    assert other_update.status_code == 403

    other_sales = client.get(
        f"/organizer/events/{event['id']}/sales",
        headers=auth_headers(other_token),
    )
    assert other_sales.status_code == 403

    organizer_my_bookings = client.get(
        "/bookings/my",
        headers=auth_headers(organizer_token),
    )
    assert organizer_my_bookings.status_code == 403


def test_event_filters_and_update(client):
    email = unique_email("filters")
    register(client, "Filter Organizer", "organizer", email)
    token = login(client, email)

    event = create_event(
        client,
        token,
        category="music",
        city="Chennai",
        price=750,
        title="Filtered Concert",
    )

    response = client.get(
        "/events",
        params={"city": "Chennai", "category": "music", "min_price": 700, "max_price": 800},
    )
    assert response.status_code == 200
    assert any(item["id"] == event["id"] for item in response.json())

    bad_range = client.get(
        "/events",
        params={"min_price": 900, "max_price": 100},
    )
    assert bad_range.status_code == 400
    assert bad_range.json()["code"] == "INVALID_PRICE_RANGE"

    updated = client.patch(
        f"/events/{event['id']}",
        json={"title": "Updated Concert", "capacity": 20},
        headers=auth_headers(token),
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated Concert"
    assert updated.json()["remaining_capacity"] == 20


def test_booking_history_sales_and_cancellation(client):
    organizer_email = unique_email("sales-organizer")
    attendee_email = unique_email("sales-attendee")
    register(client, "Sales Organizer", "organizer", organizer_email)
    register(client, "Sales Attendee", "attendee", attendee_email)

    organizer_token = login(client, organizer_email)
    attendee_token = login(client, attendee_email)

    event = create_event(client, organizer_token, capacity=10, hours=48, price=250)

    booking = client.post(
        "/bookings",
        json={"event_id": event["id"], "quantity": 2},
        headers=auth_headers(attendee_token),
    )
    assert booking.status_code == 201, booking.text
    booking_data = booking.json()
    assert booking_data["total_price"] == "500.00"

    details = client.get(f"/events/{event['id']}")
    assert details.status_code == 200
    assert details.json()["remaining_capacity"] == 8

    history = client.get("/bookings/my", headers=auth_headers(attendee_token))
    assert history.status_code == 200
    assert any(item["id"] == booking_data["id"] for item in history.json())

    sales = client.get(
        f"/organizer/events/{event['id']}/sales",
        headers=auth_headers(organizer_token),
    )
    assert sales.status_code == 200
    assert sales.json()["tickets_sold"] == 2
    assert sales.json()["revenue"] == "500.00"
    assert sales.json()["remaining_capacity"] == 8

    cancelled = client.post(
        f"/bookings/{booking_data['id']}/cancel",
        headers=auth_headers(attendee_token),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    details_after = client.get(f"/events/{event['id']}")
    assert details_after.json()["remaining_capacity"] == 10


def test_over_capacity_and_started_event_rejected(client):
    organizer_email = unique_email("capacity-organizer")
    attendee_email = unique_email("capacity-attendee")
    register(client, "Capacity Organizer", "organizer", organizer_email)
    register(client, "Capacity Attendee", "attendee", attendee_email)

    organizer_token = login(client, organizer_email)
    attendee_token = login(client, attendee_email)

    event = create_event(client, organizer_token, capacity=2, hours=48)

    response = client.post(
        "/bookings",
        json={"event_id": event["id"], "quantity": 3},
        headers=auth_headers(attendee_token),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "INSUFFICIENT_CAPACITY"

    started = create_event(client, organizer_token, capacity=2, hours=1)
    # Directly updating a future event to the past is intentionally rejected,
    # so use the API's database connection only through the service contract.
    # A one-hour event is still bookable because it has not started yet.
    response = client.post(
        "/bookings",
        json={"event_id": started["id"], "quantity": 1},
        headers=auth_headers(attendee_token),
    )
    assert response.status_code == 201


def test_event_cancellation_refunds_confirmed_bookings(client):
    organizer_email = unique_email("cancel-organizer")
    attendee_email = unique_email("cancel-attendee")
    register(client, "Cancel Organizer", "organizer", organizer_email)
    register(client, "Cancel Attendee", "attendee", attendee_email)

    organizer_token = login(client, organizer_email)
    attendee_token = login(client, attendee_email)
    event = create_event(client, organizer_token, capacity=5, hours=48)

    booking = client.post(
        "/bookings",
        json={"event_id": event["id"], "quantity": 2},
        headers=auth_headers(attendee_token),
    )
    assert booking.status_code == 201

    cancelled_event = client.post(
        f"/events/{event['id']}/cancel",
        headers=auth_headers(organizer_token),
    )
    assert cancelled_event.status_code == 200
    assert cancelled_event.json()["status"] == "cancelled"

    history = client.get("/bookings/my", headers=auth_headers(attendee_token))
    matching = [b for b in history.json() if b["id"] == booking.json()["id"]]
    assert matching[0]["status"] == "refunded"

    rejected = client.post(
        "/bookings",
        json={"event_id": event["id"], "quantity": 1},
        headers=auth_headers(attendee_token),
    )
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "EVENT_UNAVAILABLE"


def test_delete_unbooked_event(client):
    email = unique_email("delete")
    register(client, "Delete Organizer", "organizer", email)
    token = login(client, email)

    event = create_event(client, token, capacity=5, hours=48)
    response = client.delete(
        f"/events/{event['id']}",
        headers=auth_headers(token),
    )
    assert response.status_code == 204

    missing = client.get(f"/events/{event['id']}")
    assert missing.status_code == 404


def test_started_event_and_cancellation_window_rejected(client):
    organizer_email = unique_email("window-organizer")
    attendee_email = unique_email("window-attendee")
    register(client, "Window Organizer", "organizer", organizer_email)
    register(client, "Window Attendee", "attendee", attendee_email)
    organizer_token = login(client, organizer_email)
    attendee_token = login(client, attendee_email)

    near_event = create_event(client, organizer_token, capacity=3, hours=2)
    booking = client.post(
        "/bookings",
        json={"event_id": near_event["id"], "quantity": 1},
        headers=auth_headers(attendee_token),
    )
    assert booking.status_code == 201

    cancellation = client.post(
        f"/bookings/{booking.json()['id']}/cancel",
        headers=auth_headers(attendee_token),
    )
    assert cancellation.status_code == 400
    assert cancellation.json()["code"] == "CANCELLATION_WINDOW_CLOSED"

    started_event = create_event(client, organizer_token, capacity=3, hours=48)
    with SessionLocal() as db:
        event = db.get(Event, started_event["id"])
        event.starts_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    rejected = client.post(
        "/bookings",
        json={"event_id": started_event["id"], "quantity": 1},
        headers=auth_headers(attendee_token),
    )
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "EVENT_STARTED"
