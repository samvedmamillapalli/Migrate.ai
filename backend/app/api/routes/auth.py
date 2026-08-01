"""Auth HTTP routes: register / login / me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import hash_password, issue_token, verify_password
from app.config import get_settings
from app.core.exceptions import ConflictError, UnauthorizedError, ValidationError
from app.database.models import AppUser
from app.dependencies import get_db_session

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthRegisterRequest(BaseModel):
    owner_identity: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=256)


class AuthLoginRequest(BaseModel):
    owner_identity: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=128)


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    owner_identity: str
    expires_in_seconds: int


class AuthMeResponse(BaseModel):
    owner_identity: str
    auth_enabled: bool
    display_name: str | None = None


@router.get("/status")
async def auth_status() -> dict[str, object]:
    settings = get_settings()
    clerk_configured = bool(
        settings.clerk_secret_key and settings.clerk_publishable_key
    )
    return {
        "auth_enabled": bool(settings.auth_enabled) or clerk_configured,
        "register_enabled": bool(settings.auth_enabled),
        "clerk_configured": clerk_configured,
        "auth_method": "clerk" if clerk_configured else ("custom" if settings.auth_enabled else "none"),
    }


@router.post(
    "/register",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: AuthRegisterRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AuthTokenResponse:
    settings = get_settings()
    if not settings.auth_enabled:
        raise ValidationError("Auth is disabled (set AUTH_ENABLED=true)")
    secret = (settings.auth_secret or "").strip()
    if not secret:
        raise ValidationError("AUTH_SECRET is required when AUTH_ENABLED=true")

    identity = payload.owner_identity.strip()
    existing = (
        await session.execute(
            select(AppUser).where(AppUser.owner_identity == identity)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"User already exists: {identity}")

    user = AppUser(
        owner_identity=identity,
        password_hash=hash_password(payload.password, secret=secret),
        display_name=(payload.display_name or identity).strip() or identity,
    )
    session.add(user)
    await session.commit()

    ttl = int(settings.auth_token_ttl_seconds)
    token = issue_token(owner_identity=identity, secret=secret, ttl_seconds=ttl)
    return AuthTokenResponse(
        access_token=token,
        owner_identity=identity,
        expires_in_seconds=ttl,
    )


@router.post("/login", response_model=AuthTokenResponse)
async def login(
    payload: AuthLoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AuthTokenResponse:
    settings = get_settings()
    if not settings.auth_enabled:
        raise ValidationError("Auth is disabled (set AUTH_ENABLED=true)")
    secret = (settings.auth_secret or "").strip()
    if not secret:
        raise ValidationError("AUTH_SECRET is required when AUTH_ENABLED=true")

    identity = payload.owner_identity.strip()
    user = (
        await session.execute(
            select(AppUser).where(AppUser.owner_identity == identity)
        )
    ).scalar_one_or_none()
    if user is None or not verify_password(
        payload.password, user.password_hash, secret=secret
    ):
        raise UnauthorizedError("Invalid owner identity or password")

    ttl = int(settings.auth_token_ttl_seconds)
    token = issue_token(owner_identity=identity, secret=secret, ttl_seconds=ttl)
    return AuthTokenResponse(
        access_token=token,
        owner_identity=identity,
        expires_in_seconds=ttl,
    )


@router.get("/me", response_model=AuthMeResponse)
async def me(request: Request) -> AuthMeResponse:
    settings = get_settings()
    owner = getattr(request.state, "owner_identity", None)
    if settings.auth_enabled and not owner:
        raise UnauthorizedError("Not authenticated")
    return AuthMeResponse(
        owner_identity=str(owner or ""),
        auth_enabled=bool(settings.auth_enabled),
        display_name=None,
    )
