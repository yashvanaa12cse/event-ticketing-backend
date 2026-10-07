from datetime import datetime, timezone
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from .models import UserRole, EventStatus, BookingStatus


def require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone offset")
    return value.astimezone(timezone.utc)


class UserRegister(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: EmailStr
    role: UserRole


class EventCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = None
    category: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    starts_at: datetime
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    capacity: int = Field(gt=0, le=1_000_000)

    @field_validator("starts_at")
    @classmethod
    def validate_starts_at(cls, value: datetime) -> datetime:
        return require_aware_utc(value)


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    starts_at: datetime | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    capacity: int | None = Field(default=None, gt=0, le=1_000_000)

    @field_validator("starts_at")
    @classmethod
    def validate_starts_at(cls, value: datetime | None) -> datetime | None:
        return require_aware_utc(value) if value is not None else None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organizer_id: int
    title: str
    description: str | None
    category: str
    city: str
    starts_at: datetime
    price: Decimal
    capacity: int
    remaining_capacity: int
    status: EventStatus


class BookingCreate(BaseModel):
    event_id: int
    quantity: int = Field(gt=0, le=20)


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    attendee_id: int
    event_id: int
    quantity: int
    total_price: Decimal
    status: BookingStatus
    created_at: datetime
    cancelled_at: datetime | None


class SalesSummary(BaseModel):
    event_id: int
    tickets_sold: int
    revenue: Decimal
    remaining_capacity: int
    status: EventStatus


class PaginatedEvents(BaseModel):
    items: list[EventOut]
    page: int
    page_size: int
    total: int
