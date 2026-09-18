"""Password hashing and JWT helper checks. No implementation-specific hash
strings asserted — only the observable hash/verify/token contract."""

import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def test_hash_password_differs_from_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"


def test_hash_password_produces_different_hashes_for_same_password() -> None:
    # Argon2 salts each hash, so two hashes of the same password must differ.
    assert hash_password("same-password") != hash_password("same-password")


def test_verify_password_accepts_correct_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


# ---------------------------------------------------------------------------
# JWT access tokens
# ---------------------------------------------------------------------------


def test_create_and_decode_access_token_round_trips_user_id() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    assert decode_access_token(token) == user_id


def test_access_token_contains_expected_claims() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"
    assert "iat" in payload
    assert "exp" in payload


def test_expired_access_token_rejected() -> None:
    token = create_access_token(uuid.uuid4(), expires_delta=timedelta(seconds=-1))
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_malformed_token_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token("not-a-real-token")


def test_tampered_signature_token_rejected() -> None:
    token = create_access_token(uuid.uuid4())
    header, payload, signature = token.split(".")
    # Flip the *first* character of the signature, not the last: base64url's
    # final character of a segment can carry unused "don't care" bits (the
    # signature is 32 bytes, not a multiple of 3), so some replacement
    # characters there decode to identical bytes — an intermittently
    # no-op tamper. The first character has no such ambiguity.
    tampered_char = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{tampered_char}{signature[1:]}"
    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)


def test_token_signed_with_wrong_secret_rejected() -> None:
    payload = {"sub": str(uuid.uuid4()), "type": "access"}
    token = jwt.encode(payload, "a-completely-different-secret", algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_token_missing_subject_rejected() -> None:
    token = jwt.encode(
        {"type": "access"}, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_token_with_non_uuid_subject_rejected() -> None:
    token = jwt.encode(
        {"sub": "not-a-uuid", "type": "access"},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_token_with_wrong_type_claim_rejected() -> None:
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh"},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)
