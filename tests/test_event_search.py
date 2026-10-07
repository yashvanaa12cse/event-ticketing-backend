"""Tests for the `q` search parameter on GET /events.

The test database is shared and not cleaned between tests, so every test
embeds a unique token in the data it creates and searches for that token.
This keeps assertions independent of whatever other tests have left behind.
"""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Event
from tests.test_api import auth_headers, login, register, unique_email


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def organizer_token(client):
    email = unique_email("search-organizer")
    register(client, "Search Organizer", "organizer", email)
    return login(client, email)


def new_token() -> str:
    return uuid4().hex[:12]


def make_event(client, token, *, title, hours=48, description="Plain description",
               category="technology", city="Chennai", price=500, capacity=10):
    payload = {
        "title": title,
        "description": description,
        "category": category,
        "city": city,
        "starts_at": (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(),
        "price": price,
        "capacity": capacity,
    }
    response = client.post("/events", json=payload, headers=auth_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


def search(client, **params):
    response = client.get("/events", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def ids(items):
    return [item["id"] for item in items]


def test_search_matches_title(client, organizer_token):
    tok = new_token()
    match = make_event(client, organizer_token, title=f"Jazz Night {tok}")
    other = make_event(client, organizer_token, title="Unrelated Gathering")

    result = search(client, q=tok)
    assert ids(result) == [match["id"]]
    assert other["id"] not in ids(result)


def test_search_matches_description(client, organizer_token):
    tok = new_token()
    match = make_event(
        client, organizer_token,
        title="Quiet Title",
        description=f"An evening featuring {tok} performers",
    )

    result = search(client, q=tok)
    assert ids(result) == [match["id"]]


def test_search_matches_category(client, organizer_token):
    tok = new_token()
    match = make_event(client, organizer_token, title="Quiet Title", category=f"cat{tok}")

    result = search(client, q=tok)
    assert ids(result) == [match["id"]]


def test_search_is_case_insensitive(client, organizer_token):
    tok = new_token()
    by_title = make_event(client, organizer_token, title=f"Jazz Night {tok}", hours=48)
    by_description = make_event(
        client, organizer_token, title="Other", description=f"Smooth Blues {tok}", hours=49
    )

    upper_title = search(client, q=f"JAZZ NIGHT {tok}".upper())
    assert ids(upper_title) == [by_title["id"]]

    mixed_description = search(client, q=f"sMoOtH bLuEs {tok}")
    assert ids(mixed_description) == [by_description["id"]]


def test_search_trims_surrounding_whitespace(client, organizer_token):
    tok = new_token()
    match = make_event(client, organizer_token, title=f"Trim Test {tok}")

    assert ids(search(client, q=f"   {tok}   ")) == [match["id"]]


def test_search_with_category_filter(client, organizer_token):
    tok = new_token()
    music = make_event(client, organizer_token, title=f"Fest {tok}", category="music", hours=48)
    sports = make_event(client, organizer_token, title=f"Fest {tok}", category="sports", hours=49)

    result = search(client, q=tok, category="music")
    assert ids(result) == [music["id"]]
    assert sports["id"] not in ids(result)


def test_search_with_city_filter(client, organizer_token):
    tok = new_token()
    city_a = f"Alpha{tok}"
    city_b = f"Beta{tok}"
    in_a = make_event(client, organizer_token, title=f"Fest {tok}", city=city_a, hours=48)
    in_b = make_event(client, organizer_token, title=f"Fest {tok}", city=city_b, hours=49)

    result = search(client, q=tok, city=city_a)
    assert ids(result) == [in_a["id"]]
    assert in_b["id"] not in ids(result)


def test_search_with_price_filters(client, organizer_token):
    tok = new_token()
    cheap = make_event(client, organizer_token, title=f"Fest {tok}", price=100, hours=48)
    mid = make_event(client, organizer_token, title=f"Fest {tok}", price=500, hours=49)
    pricey = make_event(client, organizer_token, title=f"Fest {tok}", price=900, hours=50)

    result = search(client, q=tok, min_price=400, max_price=600)
    assert ids(result) == [mid["id"]]

    result = search(client, q=tok, min_price=400)
    assert ids(result) == [mid["id"], pricey["id"]]

    result = search(client, q=tok, max_price=600)
    assert ids(result) == [cheap["id"], mid["id"]]


def test_search_with_date_range_filters(client, organizer_token):
    tok = new_token()
    soon = make_event(client, organizer_token, title=f"Fest {tok}", hours=48)
    middle = make_event(client, organizer_token, title=f"Fest {tok}", hours=96)
    late = make_event(client, organizer_token, title=f"Fest {tok}", hours=200)

    now = datetime.now(timezone.utc)
    start = (now + timedelta(hours=72)).isoformat()
    end = (now + timedelta(hours=150)).isoformat()

    assert ids(search(client, q=tok, start_date=start, end_date=end)) == [middle["id"]]
    assert ids(search(client, q=tok, start_date=start)) == [middle["id"], late["id"]]
    assert ids(search(client, q=tok, end_date=end)) == [soon["id"], middle["id"]]


def test_search_combines_all_filters(client, organizer_token):
    tok = new_token()
    city = f"Gamma{tok}"
    target = make_event(
        client, organizer_token, title=f"Fest {tok}", category="music",
        city=city, price=500, hours=96,
    )
    # Each of these fails exactly one of the filters below.
    make_event(client, organizer_token, title=f"Fest {tok}", category="sports",
               city=city, price=500, hours=96)
    make_event(client, organizer_token, title=f"Fest {tok}", category="music",
               city=f"Delta{tok}", price=500, hours=96)
    make_event(client, organizer_token, title=f"Fest {tok}", category="music",
               city=city, price=900, hours=96)
    make_event(client, organizer_token, title=f"Fest {tok}", category="music",
               city=city, price=500, hours=200)
    make_event(client, organizer_token, title="No match here", category="music",
               city=city, price=500, hours=96)

    now = datetime.now(timezone.utc)
    result = search(
        client,
        q=tok,
        category="music",
        city=city,
        min_price=400,
        max_price=600,
        start_date=(now + timedelta(hours=72)).isoformat(),
        end_date=(now + timedelta(hours=150)).isoformat(),
    )
    assert ids(result) == [target["id"]]


def test_search_pagination(client, organizer_token):
    tok = new_token()
    created = [
        make_event(client, organizer_token, title=f"Paged {tok} #{i}", hours=48 + i)
        for i in range(5)
    ]
    expected = [event["id"] for event in created]  # ordered by start time

    page1 = search(client, q=tok, page=1, page_size=2)
    page2 = search(client, q=tok, page=2, page_size=2)
    page3 = search(client, q=tok, page=3, page_size=2)
    page4 = search(client, q=tok, page=4, page_size=2)

    assert ids(page1) == expected[0:2]
    assert ids(page2) == expected[2:4]
    assert ids(page3) == expected[4:5]
    assert page4 == []

    # Default page size still returns everything that matches.
    assert ids(search(client, q=tok)) == expected


def test_search_no_matches_returns_empty_list(client):
    result = search(client, q=f"no-such-event-{new_token()}")
    assert result == []


def test_empty_or_blank_search_is_ignored(client, organizer_token):
    tok = new_token()
    city = f"Epsilon{tok}"
    first = make_event(client, organizer_token, title="First", city=city, hours=48)
    second = make_event(client, organizer_token, title="Second", city=city, hours=49)

    baseline = search(client, city=city)
    assert ids(baseline) == [first["id"], second["id"]]

    assert search(client, city=city, q="") == baseline
    assert search(client, city=city, q="   ") == baseline


def test_search_treats_like_wildcards_literally(client, organizer_token):
    tok = new_token()
    city = f"Zeta{tok}"
    literal = make_event(client, organizer_token, title=f"Discount 100% {tok}", city=city, hours=48)
    make_event(client, organizer_token, title=f"Discount 1000 {tok}", city=city, hours=49)
    underscore = make_event(client, organizer_token, title=f"Tier_A {tok}", city=city, hours=50)
    make_event(client, organizer_token, title=f"TierXA {tok}", city=city, hours=51)

    # An unescaped "%" would also match "Discount 1000 ...".
    assert ids(search(client, city=city, q="100%")) == [literal["id"]]
    # An unescaped "_" would also match "TierXA ...".
    assert ids(search(client, city=city, q="Tier_A")) == [underscore["id"]]


def test_search_excludes_cancelled_and_started_events(client, organizer_token):
    tok = new_token()
    visible = make_event(client, organizer_token, title=f"Fest {tok}", hours=48)
    cancelled = make_event(client, organizer_token, title=f"Fest {tok}", hours=49)
    started = make_event(client, organizer_token, title=f"Fest {tok}", hours=50)

    response = client.post(f"/events/{cancelled['id']}/cancel", headers=auth_headers(organizer_token))
    assert response.status_code == 200

    with SessionLocal() as db:
        event = db.get(Event, started["id"])
        event.starts_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    assert ids(search(client, q=tok)) == [visible["id"]]


def test_search_is_public_and_needs_no_authentication(client, organizer_token):
    tok = new_token()
    match = make_event(client, organizer_token, title=f"Public {tok}")

    # `client` sends no Authorization header; GET /events stays public.
    assert ids(search(client, q=tok)) == [match["id"]]


def test_search_query_too_long_is_rejected_with_structured_error(client):
    response = client.get("/events", params={"q": "x" * 101})
    assert response.status_code == 422
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Request validation failed",
    }


def test_search_keeps_existing_filter_validation(client):
    bad_price = client.get("/events", params={"q": "anything", "min_price": 900, "max_price": 100})
    assert bad_price.status_code == 400
    assert bad_price.json()["code"] == "INVALID_PRICE_RANGE"

    now = datetime.now(timezone.utc)
    bad_dates = client.get(
        "/events",
        params={
            "q": "anything",
            "start_date": (now + timedelta(days=5)).isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
    )
    assert bad_dates.status_code == 400
    assert bad_dates.json()["code"] == "INVALID_DATE_RANGE"


def test_openapi_documents_search_parameter(client):
    spec = client.get("/openapi.json").json()
    params = {p["name"]: p for p in spec["paths"]["/events"]["get"]["parameters"]}
    assert "q" in params
    assert not params["q"].get("required", False)
    assert '"maxLength": 100' in json.dumps(params["q"]["schema"])
    assert "description" in params["q"]
