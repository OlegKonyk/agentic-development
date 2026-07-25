import os
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlmodel import select

from app.db import SessionDep
from app.models import LoginRequest, LoginResponse, User, UserRead
from app.models import Session as AuthSession

password_hash = PasswordHash.recommended()

_bearer = HTTPBearer(auto_error=False)


def session_ttl_seconds() -> int:
    return int(os.environ.get("SESSION_TTL_SECONDS", "3600"))


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return password_hash.hash("!not-a-real-password!")


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_session(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthSession:
    """Resolve the bearer token to a live DB session row; 401 on any failure."""
    if credentials is None:
        raise _unauthorized()
    try:
        token = uuid.UUID(credentials.credentials)
    except ValueError:
        raise _unauthorized() from None
    row = await session.get(AuthSession, token)
    if row is None:
        raise _unauthorized()
    if row.expires_at <= datetime.now(UTC):
        await session.delete(row)
        await session.commit()
        raise _unauthorized()
    return row


async def get_current_user(
    session: SessionDep,
    auth_session: Annotated[AuthSession, Depends(get_current_session)],
) -> User:
    user = await session.get(User, auth_session.user_id)
    if user is None:
        raise _unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

UNAUTHORIZED = {401: {"description": "Not authenticated"}}

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=LoginResponse,
    responses=UNAUTHORIZED | {400: {"description": "Malformed request body"}},
)
async def login(payload: LoginRequest, session: SessionDep) -> LoginResponse:
    # Unencodable/NUL strings are rejected as 422 at the model boundary
    # (StorableStr) before argon2 or the DB bind can turn them into a 500.
    user = (await session.exec(select(User).where(User.email == payload.email))).first()
    if user is None:
        # Burn a comparable amount of time so the response does not leak
        # whether the email exists (no user enumeration).
        password_hash.verify(payload.password, _dummy_hash())
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not password_hash.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    row = AuthSession(
        user_id=user.id,  # type: ignore[arg-type]
        expires_at=datetime.now(UTC) + timedelta(seconds=session_ttl_seconds()),
    )
    session.add(row)
    await session.commit()
    return LoginResponse(token=str(row.id), expires_at=row.expires_at)


@router.post("/logout", status_code=204, responses=UNAUTHORIZED)
async def logout(
    session: SessionDep,
    auth_session: Annotated[AuthSession, Depends(get_current_session)],
) -> None:
    await session.delete(auth_session)
    await session.commit()


@router.get("/me", response_model=UserRead, responses=UNAUTHORIZED)
async def me(user: CurrentUser) -> User:
    return user
