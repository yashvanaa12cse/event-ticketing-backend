# Event Ticketing Backend

FastAPI + PostgreSQL REST API for the DCS Web Cluster backend task.

## Requirements covered

- JWT authentication with attendee/organizer RBAC
- Validated registration, login, events and bookings
- Event CRUD with organizer ownership checks
- Event discovery by city, category, date range and price
- Event search (`q`) over title, description and category, combinable with every filter
- Pagination on event and organizer-booking lists
- Ticket booking with PostgreSQL row locking
- Booking history and cancellation
- 24-hour booking cancellation window
- Organizer booking list and sales summary
- Event cancellation with refund status propagation
- Structured JSON errors
- OpenAPI / Swagger documentation
- Automated API tests
- PostgreSQL concurrent last-seat race test
- Docker deployment

## Run with Docker

```bash
docker compose up --build
```

API: http://localhost:8000  
Swagger: http://localhost:8000/docs  
OpenAPI JSON: http://localhost:8000/openapi.json

To run the complete automated test suite against the PostgreSQL container:

```bash
docker compose exec api pytest -q
```

The race test intentionally requires PostgreSQL because SQLite does not provide the row-level locking semantics being evaluated.

## Run locally

Create a PostgreSQL database and set:

```bash
cp .env.example .env
```

Then:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Run tests:

```bash
pytest -q
```

## Main endpoints

### Auth

- `POST /auth/register`
- `POST /auth/login`

### Public events

- `GET /events`
- `GET /events/{id}`

Filters on `GET /events`:
- `q` (search text, see below)
- `city`
- `category`
- `start_date`
- `end_date`
- `min_price`
- `max_price`
- `page`
- `page_size`

Date/time query values and event start times must include a timezone offset, for example:

```text
2026-10-20T10:00:00+05:30
```

#### Searching events

`GET /events` accepts an optional `q` parameter. It is a case-insensitive substring search over the event `title`, `description` and `category`; an event matches if any of the three contains the text.

```text
GET /events?q=jazz
GET /events?q=jazz&city=Chennai&category=music&min_price=100&max_price=1000&page=1&page_size=10
```

- `q` combines with every other filter (AND) and with pagination.
- The same rules as the unfiltered list apply: only `upcoming` events that have not started are returned, ordered by start time (ties broken by id so pages are stable).
- Leading/trailing whitespace is trimmed. An empty or blank `q` is ignored, exactly as if it was not sent.
- `%` and `_` are matched literally, not as SQL wildcards.
- Maximum length is 100 characters; longer values return `422 VALIDATION_ERROR`.
- A search with no matches returns `200` and `[]`.
- The endpoint remains public; no authentication is needed.
- Filtering is done in PostgreSQL (`ILIKE ... ESCAPE`), never in Python.

**Indexing decision.** No new index was added. A substring `ILIKE '%text%'` cannot use a normal B-tree index, and the query already narrows to upcoming events through the existing `status`/`starts_at` indexes before the text match runs. A `pg_trgm` GIN index would speed up very large tables, but it needs the `pg_trgm` extension, adds write overhead, and `create_all` would not apply it to an existing database because the project has no migrations. If the events table grows large, add it manually:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX ix_events_title_trgm ON events USING gin (title gin_trgm_ops);
CREATE INDEX ix_events_description_trgm ON events USING gin (description gin_trgm_ops);
```

### Organizer

- `POST /events`
- `PATCH /events/{id}`
- `DELETE /events/{id}`
- `POST /events/{id}/cancel`
- `GET /organizer/events/{id}/bookings`
- `GET /organizer/events/{id}/sales`

An organizer can only access their own events. An event with bookings cannot be deleted because doing so would destroy booking history. Cancel it instead to propagate refund status.

### Attendee

- `POST /bookings`
- `GET /bookings/my`
- `POST /bookings/{id}/cancel`

Bookings can be cancelled only at least 24 hours before the event. The window is configurable through `CANCELLATION_WINDOW_HOURS`.

## Example registration

```json
{
  "name": "Alice",
  "email": "alice@example.com",
  "password": "password123",
  "role": "attendee"
}
```

## Concurrency strategy

The booking endpoint runs inside a database transaction and locks the selected event row using PostgreSQL `SELECT ... FOR UPDATE`.

If two attendees attempt to buy the last seat concurrently:

1. Transaction A locks the event row.
2. Transaction B waits for that row lock.
3. A checks capacity, creates its booking, decreases remaining capacity, and commits.
4. B obtains the lock and re-checks the now-current capacity.
5. B receives `409 INSUFFICIENT_CAPACITY` if no seats remain.

Therefore the capacity check and decrement cannot race each other. The automated test `tests/concurrency_test.py::test_concurrent_last_seat` verifies exactly one successful booking and one `409` for a one-seat event.

## Security

- Passwords are hashed with Argon2 via `pwdlib`.
- Passwords are never returned by API responses.
- JWT access tokens are signed with a server-side secret.
- Role checks are enforced on protected endpoints.
- Organizer event access verifies ownership.
- Booking access verifies booking ownership.
- Pydantic validates all request payloads.
- Production deployments should use a strong secret from environment/secret management and HTTPS.
- The default JWT secret is for local development only.

## Error format

Application errors use:

```json
{
  "code": "INSUFFICIENT_CAPACITY",
  "message": "Not enough seats remaining"
}
```

Validation errors use:

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Request validation failed"
}
```

Common codes:

- `EMAIL_EXISTS`
- `INVALID_CREDENTIALS`
- `INVALID_TOKEN`
- `VALIDATION_ERROR`
- `FORBIDDEN`
- `EVENT_NOT_FOUND`
- `EVENT_UNAVAILABLE`
- `EVENT_STARTED`
- `INSUFFICIENT_CAPACITY`
- `EVENT_HAS_BOOKINGS`
- `BOOKING_NOT_FOUND`
- `BOOKING_NOT_ACTIVE`
- `CANCELLATION_WINDOW_CLOSED`
- `CONFLICT`

## Project documentation

- `docs/api.md` contains endpoint examples.
- `docs/data-model.md` contains the database model and relationships.
- The concurrency strategy is documented above and tested automatically.

## Submission checklist

- [ ] Push repository to GitHub
- [ ] Add Swagger screenshots if desired
- [x] Database schema/data model
- [x] Concurrency explanation
- [x] Valid + invalid API tests
- [x] Concurrent booking race test
- [x] Dockerfile
- [x] README deployment instructions
- [x] Organizer ownership restrictions
- [x] Event cancellation refund behavior
