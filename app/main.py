from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import User, UserRole, Event, EventStatus, Booking, BookingStatus
from .schemas import (
    UserRegister, LoginRequest, TokenResponse, UserOut,
    EventCreate, EventUpdate, EventOut, BookingCreate, BookingOut,
    SalesSummary,
)
from .security import (
    hash_password, verify_password, create_access_token,
    get_current_user, require_role,
)
from .config import settings

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Event Ticketing Platform API",
    version="1.1.0",
    description="REST API for event discovery, ticket booking, and organizer management.",
)


def error(code: str, message: str) -> dict:
    return {"code": code, "message": message}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        content = detail
    else:
        content = error("HTTP_ERROR", str(detail))
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=error("VALIDATION_ERROR", "Request validation failed"),
    )


@app.exception_handler(IntegrityError)
async def integrity_exception_handler(request: Request, exc: IntegrityError):
    return JSONResponse(
        status_code=409,
        content=error("CONFLICT", "The request conflicts with existing data"),
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=error("INTERNAL_ERROR", "An unexpected server error occurred"),
    )


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(400, error("INVALID_DATETIME", "Datetime must include a timezone offset"))
    return value.astimezone(timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


LIKE_ESCAPE = "\\"


def escape_like(value: str) -> str:
    """Escape LIKE wildcards so user input is matched literally."""
    return (
        value.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/register", response_model=UserOut, status_code=201)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(409, error("EMAIL_EXISTS", "Email is already registered"))

    user = User(
        name=payload.name.strip(),
        email=str(payload.email).lower(),
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, error("EMAIL_EXISTS", "Email is already registered"))
    db.refresh(user)
    return user


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, error("INVALID_CREDENTIALS", "Invalid email or password"))
    return TokenResponse(access_token=create_access_token(user.id))


@app.get(
    "/events",
    response_model=list[EventOut],
    summary="List and search upcoming events",
    description=(
        "Public event discovery. Only upcoming events that have not started are returned, "
        "ordered by start time. All filters are optional and combine with AND. "
        "`q` runs a case-insensitive substring search over title, description and category."
    ),
)
def list_events(
    q: str | None = Query(
        default=None,
        max_length=100,
        description=(
            "Case-insensitive search text matched against event title, description and category. "
            "Leading/trailing whitespace is ignored; an empty or blank value disables search."
        ),
        examples=["jazz"],
    ),
    city: str | None = None,
    category: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    min_price: Decimal | None = Query(default=None, ge=0),
    max_price: Decimal | None = Query(default=None, ge=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(400, error("INVALID_PRICE_RANGE", "min_price cannot exceed max_price"))
    if start_date and end_date:
        start_date = normalize_datetime(start_date)
        end_date = normalize_datetime(end_date)
        if start_date > end_date:
            raise HTTPException(400, error("INVALID_DATE_RANGE", "start_date cannot exceed end_date"))
    elif start_date:
        start_date = normalize_datetime(start_date)
    elif end_date:
        end_date = normalize_datetime(end_date)

    stmt = select(Event).where(
        Event.status == EventStatus.UPCOMING,
        Event.starts_at > now_utc(),
    )
    search = q.strip() if q else ""
    if search:
        pattern = f"%{escape_like(search)}%"
        stmt = stmt.where(
            or_(
                Event.title.ilike(pattern, escape=LIKE_ESCAPE),
                Event.description.ilike(pattern, escape=LIKE_ESCAPE),
                Event.category.ilike(pattern, escape=LIKE_ESCAPE),
            )
        )
    if city:
        stmt = stmt.where(Event.city.ilike(f"%{city}%"))
    if category:
        stmt = stmt.where(Event.category.ilike(f"%{category}%"))
    if start_date:
        stmt = stmt.where(Event.starts_at >= start_date)
    if end_date:
        stmt = stmt.where(Event.starts_at <= end_date)
    if min_price is not None:
        stmt = stmt.where(Event.price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Event.price <= max_price)

    stmt = stmt.order_by(Event.starts_at, Event.id).offset((page - 1) * page_size).limit(page_size)
    return list(db.scalars(stmt).all())


@app.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(404, error("EVENT_NOT_FOUND", "Event not found"))
    return event


def get_owned_event(event_id: int, organizer: User, db: Session, lock: bool = False) -> Event:
    stmt = select(Event).where(Event.id == event_id)
    if lock:
        stmt = stmt.with_for_update()
    event = db.scalar(stmt)
    if not event:
        raise HTTPException(404, error("EVENT_NOT_FOUND", "Event not found"))
    if event.organizer_id != organizer.id:
        raise HTTPException(403, error("FORBIDDEN", "You do not own this event"))
    return event


@app.post("/events", response_model=EventOut, status_code=201)
def create_event(
    payload: EventCreate,
    organizer: User = Depends(require_role(UserRole.ORGANIZER)),
    db: Session = Depends(get_db),
):
    starts_at = normalize_datetime(payload.starts_at)
    if starts_at <= now_utc():
        raise HTTPException(400, error("INVALID_START_TIME", "Event must start in the future"))

    event = Event(
        title=payload.title.strip(),
        description=payload.description,
        category=payload.category.strip(),
        city=payload.city.strip(),
        starts_at=starts_at,
        price=payload.price,
        capacity=payload.capacity,
        remaining_capacity=payload.capacity,
        organizer_id=organizer.id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@app.patch("/events/{event_id}", response_model=EventOut)
def update_event(
    event_id: int,
    payload: EventUpdate,
    organizer: User = Depends(require_role(UserRole.ORGANIZER)),
    db: Session = Depends(get_db),
):
    event = get_owned_event(event_id, organizer, db, lock=True)
    if event.status != EventStatus.UPCOMING:
        raise HTTPException(400, error("EVENT_NOT_EDITABLE", "Only upcoming events can be edited"))

    data = payload.model_dump(exclude_unset=True)

    if "starts_at" in data:
        data["starts_at"] = normalize_datetime(data["starts_at"])
        if data["starts_at"] <= now_utc():
            raise HTTPException(400, error("INVALID_START_TIME", "Event must start in the future"))

    if "capacity" in data:
        sold = event.capacity - event.remaining_capacity
        if data["capacity"] < sold:
            raise HTTPException(400, error("CAPACITY_TOO_LOW", "Capacity cannot be below tickets already sold"))
        event.remaining_capacity = data["capacity"] - sold

    for key, value in data.items():
        if key in {"title", "category", "city"} and value is not None:
            value = value.strip()
        setattr(event, key, value)

    db.commit()
    db.refresh(event)
    return event


@app.delete("/events/{event_id}", status_code=204)
def delete_event(
    event_id: int,
    organizer: User = Depends(require_role(UserRole.ORGANIZER)),
    db: Session = Depends(get_db),
):
    event = get_owned_event(event_id, organizer, db, lock=True)
    if event.status != EventStatus.UPCOMING:
        raise HTTPException(400, error("EVENT_NOT_DELETABLE", "Only upcoming events can be deleted"))
    if db.scalar(select(func.count(Booking.id)).where(Booking.event_id == event.id)):
        raise HTTPException(
            409,
            error("EVENT_HAS_BOOKINGS", "An event with bookings cannot be deleted; cancel it instead"),
        )
    db.delete(event)
    db.commit()
    return None


@app.post("/events/{event_id}/cancel", response_model=EventOut)
def cancel_event(
    event_id: int,
    organizer: User = Depends(require_role(UserRole.ORGANIZER)),
    db: Session = Depends(get_db),
):
    event = get_owned_event(event_id, organizer, db, lock=True)
    if event.status != EventStatus.UPCOMING:
        raise HTTPException(400, error("EVENT_ALREADY_CLOSED", "Event is already closed"))

    event.status = EventStatus.CANCELLED
    for booking in event.bookings:
        if booking.status == BookingStatus.CONFIRMED:
            booking.status = BookingStatus.REFUNDED

    db.commit()
    db.refresh(event)
    return event


@app.post("/bookings", response_model=BookingOut, status_code=201)
def create_booking(
    payload: BookingCreate,
    attendee: User = Depends(require_role(UserRole.ATTENDEE)),
    db: Session = Depends(get_db),
):
    # PostgreSQL row-level lock serializes all bookings for this event.
    event = db.scalar(
        select(Event).where(Event.id == payload.event_id).with_for_update()
    )
    if not event:
        raise HTTPException(404, error("EVENT_NOT_FOUND", "Event not found"))

    if event.status != EventStatus.UPCOMING:
        raise HTTPException(400, error("EVENT_UNAVAILABLE", "Event is cancelled or completed"))
    if event.starts_at <= now_utc():
        raise HTTPException(400, error("EVENT_STARTED", "Cannot book an event that has started"))
    if event.remaining_capacity < payload.quantity:
        raise HTTPException(409, error("INSUFFICIENT_CAPACITY", "Not enough seats remaining"))

    event.remaining_capacity -= payload.quantity
    booking = Booking(
        attendee_id=attendee.id,
        event_id=event.id,
        quantity=payload.quantity,
        total_price=Decimal(event.price) * payload.quantity,
        status=BookingStatus.CONFIRMED,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


@app.get("/bookings/my", response_model=list[BookingOut])
def my_bookings(
    attendee: User = Depends(require_role(UserRole.ATTENDEE)),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Booking)
        .where(Booking.attendee_id == attendee.id)
        .order_by(Booking.created_at.desc())
    )
    return list(db.scalars(stmt).all())


@app.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(
    booking_id: int,
    attendee: User = Depends(require_role(UserRole.ATTENDEE)),
    db: Session = Depends(get_db),
):
    booking = db.scalar(
        select(Booking).where(Booking.id == booking_id).with_for_update()
    )
    if not booking:
        raise HTTPException(404, error("BOOKING_NOT_FOUND", "Booking not found"))
    if booking.attendee_id != attendee.id:
        raise HTTPException(403, error("FORBIDDEN", "You do not own this booking"))
    if booking.status != BookingStatus.CONFIRMED:
        raise HTTPException(400, error("BOOKING_NOT_ACTIVE", "Booking is not active"))

    event = db.scalar(select(Event).where(Event.id == booking.event_id).with_for_update())
    cancellation_deadline = event.starts_at - timedelta(hours=settings.cancellation_window_hours)
    if now_utc() > cancellation_deadline:
        raise HTTPException(
            400,
            error(
                "CANCELLATION_WINDOW_CLOSED",
                f"Bookings can only be cancelled at least {settings.cancellation_window_hours} hours before the event",
            ),
        )
    if event.status != EventStatus.UPCOMING:
        raise HTTPException(400, error("EVENT_UNAVAILABLE", "Event is cancelled or completed"))

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = now_utc()
    event.remaining_capacity += booking.quantity
    db.commit()
    db.refresh(booking)
    return booking


@app.get("/organizer/events/{event_id}/bookings", response_model=list[BookingOut])
def organizer_bookings(
    event_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    organizer: User = Depends(require_role(UserRole.ORGANIZER)),
    db: Session = Depends(get_db),
):
    event = get_owned_event(event_id, organizer, db)
    stmt = (
        select(Booking)
        .where(Booking.event_id == event.id)
        .order_by(Booking.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(db.scalars(stmt).all())


@app.get("/organizer/events/{event_id}/sales", response_model=SalesSummary)
def sales_summary(
    event_id: int,
    organizer: User = Depends(require_role(UserRole.ORGANIZER)),
    db: Session = Depends(get_db),
):
    event = get_owned_event(event_id, organizer, db)
    sold, revenue = db.execute(
        select(
            func.coalesce(func.sum(Booking.quantity), 0),
            func.coalesce(func.sum(Booking.total_price), 0),
        ).where(
            Booking.event_id == event.id,
            Booking.status == BookingStatus.CONFIRMED,
        )
    ).one()
    return SalesSummary(
        event_id=event.id,
        tickets_sold=int(sold or 0),
        revenue=revenue or Decimal("0.00"),
        remaining_capacity=event.remaining_capacity,
        status=event.status,
    )
