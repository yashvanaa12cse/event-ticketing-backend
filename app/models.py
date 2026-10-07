from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Integer, DateTime, ForeignKey, Numeric, Enum, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base
import enum

class UserRole(str, enum.Enum):
    ATTENDEE = "attendee"
    ORGANIZER = "organizer"

class EventStatus(str, enum.Enum):
    UPCOMING = "upcoming"
    CANCELLED = "cancelled"
    COMPLETED = "completed"

class BookingStatus(str, enum.Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    events: Mapped[list["Event"]] = relationship(back_populates="organizer")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="attendee")

class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    organizer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text())
    category: Mapped[str] = mapped_column(String(100), index=True)
    city: Mapped[str] = mapped_column(String(100), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    capacity: Mapped[int] = mapped_column(Integer)
    remaining_capacity: Mapped[int] = mapped_column(Integer)
    status: Mapped[EventStatus] = mapped_column(Enum(EventStatus), default=EventStatus.UPCOMING, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    organizer: Mapped["User"] = relationship(back_populates="events")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="event", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_events_city_category_starts", "city", "category", "starts_at"),
    )

class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    attendee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.CONFIRMED, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    attendee: Mapped["User"] = relationship(back_populates="bookings")
    event: Mapped["Event"] = relationship(back_populates="bookings")
