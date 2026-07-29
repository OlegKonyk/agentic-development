from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AfterValidator, BaseModel, field_serializer
from pydantic import Field as PydanticField
from sqlalchemy import DateTime, Index
from sqlmodel import Field, SQLModel

Status = Literal["todo", "doing", "done"]
ReminderStatus = Literal["none", "pending", "sent", "failed"]
DeliveryOutcome = Literal["accepted", "failed"]
ReminderHealthState = Literal["healthy", "degraded"]


def _require_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("title must contain a non-whitespace character")
    return value


def _require_storable(value: str) -> str:
    # JSON admits lone UTF-16 surrogates and NUL, but neither survives the trip
    # to Postgres: surrogates fail UTF-8 encoding and NUL is rejected by the
    # text codec — unguarded, both crash asyncpg's bind into a 500
    # (Schemathesis findings: login email, task fields).
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("string must not contain unpaired surrogates") from None
    if "\x00" in value:
        raise ValueError("string must not contain NUL characters")
    return value


StorableStr = Annotated[str, AfterValidator(_require_storable)]

Title = Annotated[
    str,
    PydanticField(min_length=1, max_length=200),
    AfterValidator(_require_storable),
    AfterValidator(_require_non_blank),
]

# Larger than Title's 200-char max so the web layer can clamp an over-long
# typed search term to this bound without changing results: no term longer
# than a title's max length can ever be a substring of one.
SEARCH_MAX_LENGTH = 1000

SearchTerm = Annotated[str, AfterValidator(_require_storable)]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def rfc3339(value: datetime) -> str:
    """The API contract promises RFC 3339 `Z` timestamps."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat().replace("+00:00", "Z")


def _require_future(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    if value <= _utcnow():
        raise ValueError("due_at must be in the future")
    return value


# Validated on create/update: due_at is optional, but when present must be future.
DueAt = Annotated[datetime, AfterValidator(_require_future)]


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(max_length=255, unique=True, index=True)
    password_hash: str
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    expires_at: datetime = Field(sa_type=DateTime(timezone=True))


class Task(SQLModel, table=True):
    __tablename__ = "tasks"
    # Serves the board's ordered page: equality on owner_id, then the exact
    # (due_at ASC NULLS LAST, id ASC) order, so a page is an index range scan
    # rather than a sort of the owner's whole task set.
    __table_args__ = (Index("ix_tasks_owner_due_at_id", "owner_id", "due_at", "id"),)

    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="users.id", index=True)
    title: str = Field(max_length=200)
    description: str = ""
    status: str = "todo"
    due_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True), index=True)
    reminder_status: str = "none"
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))


class WebhookEvent(SQLModel, table=True):
    __tablename__ = "webhook_events"

    # Primary key is the vendor's event id (`webhook-id` header): dedupe by unique insert.
    id: str = Field(primary_key=True, max_length=255)
    received_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    payload: str = ""


class ReminderDelivery(SQLModel, table=True):
    __tablename__ = "reminder_deliveries"

    id: int | None = Field(default=None, primary_key=True)
    # Deliberately NO foreign key to tasks.id: a delivery outcome outlives the
    # task, and an FK would make DELETE /api/tasks/{id} fail once a reminder
    # had been attempted for it.
    task_id: int = Field(index=True)
    outcome: str = Field(max_length=16)
    at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True), index=True)


class TaskCreate(BaseModel):
    title: Title
    description: StorableStr = ""
    due_at: DueAt | None = None


class TaskUpdate(BaseModel):
    title: Title | None = None
    description: StorableStr | None = None
    status: Status | None = None
    due_at: DueAt | None = None


class TaskRead(BaseModel):
    id: int
    title: str
    description: str
    status: Status
    due_at: datetime | None
    reminder_status: ReminderStatus
    created_at: datetime

    @field_serializer("created_at")
    def _created_rfc3339(self, value: datetime) -> str:
        return rfc3339(value)

    @field_serializer("due_at")
    def _due_rfc3339(self, value: datetime | None) -> str | None:
        return None if value is None else rfc3339(value)


class TaskPage(BaseModel):
    items: list[TaskRead]
    total: int
    limit: int
    offset: int


class ReminderHealthRead(BaseModel):
    state: ReminderHealthState
    window_seconds: int


class UserRead(BaseModel):
    id: int
    email: str


class LoginRequest(BaseModel):
    email: StorableStr
    password: StorableStr


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime

    @field_serializer("expires_at")
    def _expires_rfc3339(self, value: datetime) -> str:
        return rfc3339(value)
