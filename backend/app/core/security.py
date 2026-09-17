"""Authentication and security helpers: password hashing and JWT tokens.

The database remains the source of truth for identity — a valid JWT proves
who the client claims to be, not that the account still exists.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

_password_hash = PasswordHash.recommended()  # Argon2id

_ACCESS_TOKEN_TYPE = "access"


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _password_hash.verify(plain_password, password_hash)


class InvalidTokenError(Exception):
    """Missing, malformed, expired, tampered, or otherwise untrustworthy token."""


def create_access_token(user_id: uuid.UUID, expires_delta: timedelta | None = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": expire,
        "type": _ACCESS_TOKEN_TYPE,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Validate an access token and return its subject user id.

    Raises InvalidTokenError for anything untrustworthy — expired, malformed,
    bad signature, wrong token type, missing/invalid subject — never returns
    a partially-trusted result.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Invalid or expired token") from exc

    if payload.get("type") != _ACCESS_TOKEN_TYPE:
        raise InvalidTokenError("Unexpected token type")

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise InvalidTokenError("Token missing subject")

    try:
        return uuid.UUID(subject)
    except ValueError as exc:
        raise InvalidTokenError("Token subject is not a valid user id") from exc
