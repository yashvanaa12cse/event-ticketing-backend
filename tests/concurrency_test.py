from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import app
from tests.test_api import (
    auth_headers,
    create_event,
    login,
    register,
    unique_email,
)


def test_concurrent_last_seat():
    """
    PostgreSQL integration race test required by the assignment.

    Two independent requests attempt to book the same final seat at the same
    time. SELECT ... FOR UPDATE on the event row must serialize them, so
    exactly one succeeds and the other receives 409.
    """
    organizer_email = unique_email("race-organizer")
    attendee_a_email = unique_email("race-a")
    attendee_b_email = unique_email("race-b")

    with TestClient(app) as setup_client:
        register(setup_client, "Race Organizer", "organizer", organizer_email)
        register(setup_client, "Race A", "attendee", attendee_a_email)
        register(setup_client, "Race B", "attendee", attendee_b_email)

        organizer_token = login(setup_client, organizer_email)
        token_a = login(setup_client, attendee_a_email)
        token_b = login(setup_client, attendee_b_email)
        event = create_event(setup_client, organizer_token, capacity=1, hours=48)

    def book(token):
        with TestClient(app) as client:
            return client.post(
                "/bookings",
                json={"event_id": event["id"], "quantity": 1},
                headers=auth_headers(token),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(book, [token_a, token_b]))

    assert sorted(response.status_code for response in responses) == [201, 409]

    with TestClient(app) as verify_client:
        details = verify_client.get(f"/events/{event['id']}")
        assert details.status_code == 200
        assert details.json()["remaining_capacity"] == 0
