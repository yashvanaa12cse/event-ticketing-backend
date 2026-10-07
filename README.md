# Event Ticketing Backend

FastAPI + PostgreSQL REST API for the DCS Web Cluster backend task.

## Requirements covered

* JWT authentication with attendee/organizer RBAC
* Validated registration, login, events and bookings
* Event CRUD with organizer ownership checks
* Event discovery by city, category, date range and price
* Event search (`q`) over title, description and category, combinable with every filter
* Pagination on event and organizer-booking lists
* Ticket booking with PostgreSQL row locking
* Booking history and cancellation
* 24-hour booking cancellation window
* Organizer booking list and sales summary
* Event cancellation with refund status propagation
* Structured JSON errors
* OpenAPI / Swagger documentation
* Automated API tests
* PostgreSQL concurrent last-seat race test
* Docker deployment

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



## Live Deployment

\- \*\*Deployed API:\*\* https://event-ticketing-backend-qzfy.onrender.com

\- \*\*Swagger UI:\*\* https://event-ticketing-backend-qzfy.onrender.com/docs

## Run locally

Create a PostgreSQL database and set:

```bash
cp .env.example .env
```

Then:

```bash
python -m venv .venv
# Windows:
.venv\\\\Scripts\\\\activate
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

* `POST /auth/register`
* `POST /auth/login`

### Public events

* `GET /events`
* `GET /events/{id}`

Filters on `GET /events`:

* `q` (search text, see below)
* `city`
* `category`
* `start\\\_date`
* `end\\\_date`
* `min\\\_price`
* `max\\\_price`
* `page`
* `page\\\_size`

Date/time query values and event start times must include a timezone offset, for example:

```text
2026-10-20T10:00:00+05:30
```

#### Searching events

`GET /events` accepts an optional `q` parameter. It is a case-insensitive substring search over the event `title`, `description` and `category`; an event matches if any of the three contains the text.

```text
GET /events?q=jazz
GET /events?q=jazz\\\&city=Chennai\\\&category=music\\\&min\\\_price=100\\\&max\\\_price=1000\\\&page=1\\\&page\\\_size=10
```

* `q` combines with every other filter (AND) and with pagination.
* The same rules as the unfiltered list apply: only `upcoming` events that have not started are returned, ordered by start time (ties broken by id so pages are stable).
* Leading/trailing whitespace is trimmed. An empty or blank `q` is ignored, exactly as if it was not sent.
* `%` and `\\\_` are matched literally, not as SQL wildcards.
* Maximum length is 100 characters; longer values return `422 VALIDATION\\\_ERROR`.
* A search with no matches returns `200` and `\\\[]`.
* The endpoint remains public; no authentication is needed.
* Filtering is done in PostgreSQL (`ILIKE ... ESCAPE`), never in Python.

**Indexing decision.** No new index was added. A substring `ILIKE '%text%'` cannot use a normal B-tree index, and the query already narrows to upcoming events through the existing `status`/`starts\\\_at` indexes before the text match runs. A `pg\\\_trgm` GIN index would speed up very large tables, but it needs the `pg\\\_trgm` extension, adds write overhead, and `create\\\_all` would not apply it to an existing database because the project has no migrations. If the events table grows large, add it manually:

```sql
CREATE EXTENSION IF NOT EXISTS pg\\\_trgm;
CREATE INDEX ix\\\_events\\\_title\\\_trgm ON events USING gin (title gin\\\_trgm\\\_ops);
CREATE INDEX ix\\\_events\\\_description\\\_trgm ON events USING gin (description gin\\\_trgm\\\_ops);
```

### Organizer

* `POST /events`
* `PATCH /events/{id}`
* `DELETE /events/{id}`
* `POST /events/{id}/cancel`
* `GET /organizer/events/{id}/bookings`
* `GET /organizer/events/{id}/sales`

An organizer can only access their own events. An event with bookings cannot be deleted because doing so would destroy booking history. Cancel it instead to propagate refund status.

### Attendee

* `POST /bookings`
* `GET /bookings/my`
* `POST /bookings/{id}/cancel`

Bookings can be cancelled only at least 24 hours before the event. The window is configurable through `CANCELLATION\\\_WINDOW\\\_HOURS`.

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
5. B receives `409 INSUFFICIENT\\\_CAPACITY` if no seats remain.

Therefore the capacity check and decrement cannot race each other. The automated test `tests/concurrency\\\_test.py::test\\\_concurrent\\\_last\\\_seat` verifies exactly one successful booking and one `409` for a one-seat event.

## Security

* Passwords are hashed with Argon2 via `pwdlib`.
* Passwords are never returned by API responses.
* JWT access tokens are signed with a server-side secret.
* Role checks are enforced on protected endpoints.
* Organizer event access verifies ownership.
* Booking access verifies booking ownership.
* Pydantic validates all request payloads.
* Production deployments should use a strong secret from environment/secret management and HTTPS.
* The default JWT secret is for local development only.

## Error format

Application errors use:

```json
{
  "code": "INSUFFICIENT\\\_CAPACITY",
  "message": "Not enough seats remaining"
}
```

Validation errors use:

```json
{
  "code": "VALIDATION\\\_ERROR",
  "message": "Request validation failed"
}
```

Common codes:

* `EMAIL\\\_EXISTS`
* `INVALID\\\_CREDENTIALS`
* `INVALID\\\_TOKEN`
* `VALIDATION\\\_ERROR`
* `FORBIDDEN`
* `EVENT\\\_NOT\\\_FOUND`
* `EVENT\\\_UNAVAILABLE`
* `EVENT\\\_STARTED`
* `INSUFFICIENT\\\_CAPACITY`
* `EVENT\\\_HAS\\\_BOOKINGS`
* `BOOKING\\\_NOT\\\_FOUND`
* `BOOKING\\\_NOT\\\_ACTIVE`
* `CANCELLATION\\\_WINDOW\\\_CLOSED`
* `CONFLICT`

## Project documentation

* `docs/api.md` contains endpoint examples.
* `docs/data-model.md` contains the database model and relationships.
* The concurrency strategy is documented above and tested automatically.

## Submission checklist

* \[x] Push repository to GitHub
* \[ ] Add Swagger screenshots if desired
* \[x] Database schema/data model
* \[x] Concurrency explanation
* \[x] Valid + invalid API tests
* \[x] Concurrent booking race test
* \[x] Dockerfile
* \[x] README deployment instructions
* \[x] Organizer ownership restrictions
* \[x] Event cancellation refund behavior

