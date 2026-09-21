"""API-key and browser-session authentication for catalog administration."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .config import get_settings

COOKIE_NAME = "food_catalog_admin_session"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
LOGIN_WINDOW_SECONDS = 300
LOGIN_ATTEMPTS = 5
_login_failures: dict[str, deque[float]] = defaultdict(deque)
_session_epoch = secrets.token_urlsafe(24)
_revoked_sessions: dict[str, int] = {}


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


router = APIRouter(prefix="/v1/admin/session", tags=["administration-session"])


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, *, iterations: int = 600000, salt: bytes | None = None) -> str:
    if not password:
        raise ValueError("password cannot be empty")
    salt = salt or secrets.token_bytes(18)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64_encode(salt)}${_b64_encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_iterations, raw_salt, raw_digest = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _b64_decode(raw_salt), int(raw_iterations)
        )
        return hmac.compare_digest(digest, _b64_decode(raw_digest))
    except (ValueError, TypeError):
        return False


def _sign(payload: dict) -> str:
    body = _b64_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(get_settings().session_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64_encode(signature)}"


def _decode_session(token: str | None) -> dict:
    try:
        body, raw_signature = (token or "").split(".", 1)
        expected = hmac.new(get_settings().session_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64_decode(raw_signature)):
            raise ValueError
        payload = json.loads(_b64_decode(body))
        now = int(time.time())
        token_id = hashlib.sha256((token or "").encode()).hexdigest()
        for revoked_id, expiry in list(_revoked_sessions.items()):
            if expiry <= now:
                _revoked_sessions.pop(revoked_id, None)
        if (
            payload.get("exp", 0) <= now
            or payload.get("username") != get_settings().admin_username
            or payload.get("epoch") != _session_epoch
            or token_id in _revoked_sessions
        ):
            raise ValueError
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Invalid or expired administrator session")


def _check_key(provided: str | None, expected: str) -> bool:
    return bool(provided) and hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not _check_key(x_api_key, get_settings().api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")


def require_admin_access(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_csrf_token: str | None = Header(default=None),
) -> str:
    if _check_key(x_api_key, get_settings().admin_api_key):
        return "admin-api-key"
    payload = _decode_session(request.cookies.get(COOKIE_NAME))
    if request.method in UNSAFE_METHODS and not (
        x_csrf_token and hmac.compare_digest(x_csrf_token, payload.get("csrf", ""))
    ):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return payload["username"]


def _origin_is_allowed(request: Request) -> bool:
    if get_settings().environment != "production":
        return True
    origin = request.headers.get("origin", "")
    parsed = urlsplit(origin)
    return parsed.scheme == "https" and parsed.netloc == request.headers.get("host", "")


def _rate_key(request: Request, username: str) -> str:
    client = request.client.host if request.client else "unknown"
    return hashlib.sha256(f"{client}\0{username}".encode()).hexdigest()


def _allow_login(key: str) -> bool:
    now = time.monotonic()
    failures = _login_failures[key]
    while failures and failures[0] <= now - LOGIN_WINDOW_SECONDS:
        failures.popleft()
    return len(failures) < LOGIN_ATTEMPTS


@router.post("")
def login(payload: LoginRequest, request: Request, response: Response):
    if not _origin_is_allowed(request):
        raise HTTPException(status_code=403, detail="HTTPS same-origin login required")
    settings = get_settings()
    key = _rate_key(request, payload.username)
    if not _allow_login(key):
        raise HTTPException(status_code=429, detail="Too many login attempts; try again later")
    valid_user = hmac.compare_digest(payload.username.encode(), settings.admin_username.encode())
    valid_password = verify_password(payload.password, settings.admin_password_hash)
    if not (valid_user and valid_password):
        _login_failures[key].append(time.monotonic())
        raise HTTPException(status_code=401, detail="Invalid username or password")
    _login_failures.pop(key, None)
    csrf = secrets.token_urlsafe(32)
    expires = int(time.time()) + settings.session_ttl_seconds
    token = _sign({
        "username": settings.admin_username, "csrf": csrf, "exp": expires,
        "epoch": _session_epoch, "nonce": secrets.token_urlsafe(18),
    })
    response.set_cookie(
        COOKIE_NAME, token, max_age=settings.session_ttl_seconds, path="/",
        secure=settings.environment == "production", httponly=True, samesite="strict",
    )
    return {"username": settings.admin_username, "csrf_token": csrf, "expires_at": expires}


@router.get("")
def current_session(request: Request):
    payload = _decode_session(request.cookies.get(COOKIE_NAME))
    return {"username": payload["username"], "csrf_token": payload["csrf"], "expires_at": payload["exp"]}


@router.delete("")
def logout(request: Request, response: Response, x_csrf_token: str = Header(alias="X-CSRF-Token")):
    token = request.cookies.get(COOKIE_NAME)
    payload = _decode_session(token)
    if not hmac.compare_digest(x_csrf_token, payload["csrf"]):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    _revoked_sessions[hashlib.sha256((token or "").encode()).hexdigest()] = payload["exp"]
    response.delete_cookie(
        COOKIE_NAME, path="/", secure=get_settings().environment == "production",
        httponly=True, samesite="strict",
    )
    return {"status": "logged_out"}


# Existing API clients may keep authenticating with FOOD_CATALOG_ADMIN_API_KEY.
require_admin_key = require_admin_access
