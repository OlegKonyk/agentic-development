from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AfterValidator, BaseModel, field_serializer
from pydantic import Field as PydanticField
from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel

Status = Literal["todo", "doing", "done"]
ReminderStatus = Literal["none", "pending", "sent", "failed"]


def _require_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("title must contain a non-whitespace character")
    return value


Title = Annotated[
    str, PydanticField(min_length=1, max_length=200), AfterValidator(_require_non_blank)
]


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


class TaskCreate(BaseModel):
    title: Title
    description: str = ""
    due_at: DueAt | None = None


class TaskUpdate(BaseModel):
    title: Title | None = None
    description: str | None = None
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


class UserRead(BaseModel):
    id: int
    email: str


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime

    @field_serializer("expires_at")
    def _expires_rfc3339(self, value: datetime) -> str:
        return rfc3339(value)
