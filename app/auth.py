from hmac import compare_digest

from fastapi import Header, HTTPException

from .config import get_settings


def _check_key(provided: str | None, expected: str) -> None:
    if not provided or not compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid API key")


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    _check_key(x_api_key, get_settings().api_key)


def require_admin_key(x_api_key: str | None = Header(default=None)) -> None:
    _check_key(x_api_key, get_settings().admin_api_key)
