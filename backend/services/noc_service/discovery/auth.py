"""
Session-based authentication for the discovery dashboard / API.

Uses Starlette's signed-cookie SessionMiddleware. Passwords are verified
against the SQLite ``users`` table with bcrypt hashes (via ``core.security``).
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status


def login_user(request: Request, username: str) -> None:
    request.session["user"] = username


def logout_user(request: Request) -> None:
    request.session.pop("user", None)


def current_user(request: Request) -> str | None:
    return request.session.get("user")


def require_user(request: Request) -> str:
    """FastAPI dependency: 401 if there is no authenticated session."""
    user = current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


AuthUser = Depends(require_user)
