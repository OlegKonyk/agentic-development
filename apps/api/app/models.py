from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, field_serializer
from pydantic import Field as PydanticField
from sqlmodel import Field, SQLModel

Status = Literal["todo", "doing", "done"]

Title = Annotated[str, PydanticField(min_length=1, max_length=200)]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Task(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    description: str = ""
    status: str = "todo"
    created_at: datetime = Field(default_factory=_utcnow)


class TaskCreate(BaseModel):
    title: Title
    description: str = ""


class TaskUpdate(BaseModel):
    title: Title | None = None
    description: str | None = None
    status: Status | None = None


class TaskRead(BaseModel):
    id: int
    title: str
    description: str
    status: Status
    created_at: datetime

    @field_serializer("created_at")
    def _rfc3339(self, value: datetime) -> str:
        # SQLite round-trips drop tzinfo; the API contract promises RFC 3339.
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat().replace("+00:00", "Z")
