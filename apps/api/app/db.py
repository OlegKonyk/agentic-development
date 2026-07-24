import os
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import SQLModel, create_engine


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "./data"))


def create_db_engine(directory: Path | None = None) -> Engine:
    """Create the SQLite engine at $DATA_DIR/tasks.db and ensure tables exist."""
    target = directory or data_dir()
    target.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{target / 'tasks.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    return engine
