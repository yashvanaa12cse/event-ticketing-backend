# API Specification

Base URL:

`http://localhost:8000`

Swagger UI:

`/docs`

OpenAPI:

`/openapi.json`

## Authentication

Protected endpoints use:

`Authorization: Bearer <access_token>`

### POST /auth/register

Request:

```json
{
  "name": "Alice",
  "email": "alice@example.com",
  "password": "password123",
  "role": "attendee"
}
```

Roles are `attendee` and `organizer`.

Success: `201 Created`

### POST /auth/login

Request:

```json
{
  "email": "alice@example.com",
  "password": "password123"
}
```

Response:

```json
{
  "access_token": "...",
  "token_type": "bearer"
}
```

## Events

### GET /events

Public event discovery.

Supported query parameters:

- `q`
- `city`
- `category`
- `start_date`
- `end_date`
- `min_price`
- `max_price`
- `page`
- `page_size`

Example:

`GET /events?city=Chennai&category=concert&min_price=100&max_price=1000&page=1&page_size=20`

Only upcoming events that have not started are returned, ordered by start time.

#### Search (`q`)

`q` is an optional case-insensitive substring search over event `title`, `description` and `category`.

Example:

`GET /events?q=jazz&city=Chennai&min_price=100&max_price=1000&page=1&page_size=10`

Behaviour:

- Combines (AND) with `city`, `category`, `start_date`, `end_date`, `min_price`, `max_price`, `page` and `page_size`.
- Leading/trailing whitespace is trimmed; an empty or blank `q` is ignored.
- `%` and `_` in `q` are matched literally.
- Maximum 100 characters; longer input returns `422` with `VALIDATION_ERROR`.
- No matches returns `200` with `[]`.
- Public endpoint: no authentication required.

Example response for `GET /events?q=jazz`:

```json
[
  {
    "id": 7,
    "organizer_id": 2,
    "title": "Jazz Night",
    "description": "Live quartet at the riverside",
    "category": "music",
    "city": "Chennai",
    "starts_at": "2026-10-20T04:30:00Z",
    "price": "499.00",
    "capacity": 100,
    "remaining_capacity": 88,
    "status": "upcoming"
  }
]
```

### GET /events/{id}

Returns event details and remaining capacity.

### POST /events

Organizer only.

Example:

```json
{
  "title": "Tech Conference",
  "description": "Conference for students and developers",
  "category": "technology",
  "city": "Chennai",
  "starts_at": "2026-10-20T10:00:00+05:30",
  "price": 499.00,
  "capacity": 100
}
```

### PATCH /events/{id}

Organizer owner only. Capacity cannot be reduced below tickets already sold.

### DELETE /events/{id}

Organizer owner only. An event with bookings returns `409 EVENT_HAS_BOOKINGS`; cancel the event instead.

### POST /events/{id}/cancel

Organizer owner only.

The event becomes `cancelled` and confirmed bookings become `refunded`.

## Bookings

### POST /bookings

Attendee only.

```json
{
  "event_id": 1,
  "quantity": 2
}
```

Success: `201 Created`

Insufficient capacity: `409 Conflict`

Started/cancelled event: `400 Bad Request`

The endpoint locks the event row with PostgreSQL `SELECT ... FOR UPDATE` before checking capacity.

### GET /bookings/my

Attendee only. Returns the attendee's booking history.

### POST /bookings/{id}/cancel

Attendee only and booking owner only.

Cancellation is allowed only at least 24 hours before the event. The configured window is `CANCELLATION_WINDOW_HOURS`.

## Organizer dashboard

### GET /organizer/events/{id}/bookings

Organizer owner only.

Supports `page` and `page_size`.

### GET /organizer/events/{id}/sales

Organizer owner only.

Response:

```json
{
  "event_id": 1,
  "tickets_sold": 12,
  "revenue": "5988.00",
  "remaining_capacity": 88,
  "status": "upcoming"
}
```

## Error responses

Application errors:

```json
{
  "code": "FORBIDDEN",
  "message": "You do not own this event"
}
```

Validation errors:

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Request validation failed"
}
```

Typical status codes:

- `201` created
- `200` success
- `204` deleted
- `400` invalid business request
- `401` missing/invalid authentication
- `403` insufficient role or ownership
- `404` resource not found
- `409` state/data conflict
- `422` malformed request
- `500` unexpected server error
