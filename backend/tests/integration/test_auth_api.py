"""End-to-end auth API tests: register -> login -> Bearer-protected /me.

Uses the real local PostgreSQL instance (via the app's own get_db
dependency). Uses httpx.AsyncClient + ASGITransport rather than Starlette's
synchronous TestClient: TestClient runs the app on a background thread via
an anyio portal, and mixing that with direct async DB calls in the same
test against one shared engine/connection pool causes real cross-event-loop
connection-pool races ("another operation is in progress"). Running the
whole test as native async against a single event loop avoids that.
"""

import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import delete

from app.core.security import create_access_token
from app.database.postgres import async_session_maker
from app.main import app
from app.models import User


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _cleanup_user_by_email(email: str) -> None:
    async with async_session_maker() as session:
        await session.execute(delete(User).where(User.email == email))
        await session.commit()


def _unique_email() -> str:
    return f"{uuid.uuid4()}@example.com"


async def test_register_returns_user_without_password_fields(client: httpx.AsyncClient) -> None:
    email = _unique_email()
    try:
        response = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "correcthorse123"}
        )
        assert response.status_code == 201
        body = response.json()
        assert body["email"] == email
        assert "password" not in body
        assert "password_hash" not in body
    finally:
        await _cleanup_user_by_email(email)


async def test_register_duplicate_email_returns_409(client: httpx.AsyncClient) -> None:
    email = _unique_email()
    try:
        first = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "correcthorse123"}
        )
        assert first.status_code == 201

        second = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "anotherpassword123"}
        )
        assert second.status_code == 409
    finally:
        await _cleanup_user_by_email(email)


async def test_register_rejects_short_password(client: httpx.AsyncClient) -> None:
    email = _unique_email()
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "short"}
    )
    assert response.status_code == 422


async def test_login_with_correct_password_returns_bearer_token(client: httpx.AsyncClient) -> None:
    email = _unique_email()
    try:
        await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "correcthorse123"}
        )

        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "correcthorse123"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert isinstance(body["access_token"], str) and body["access_token"]
    finally:
        await _cleanup_user_by_email(email)


async def test_login_with_wrong_password_returns_401(client: httpx.AsyncClient) -> None:
    email = _unique_email()
    try:
        await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "correcthorse123"}
        )

        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong-password"}
        )
        assert response.status_code == 401
    finally:
        await _cleanup_user_by_email(email)


async def test_login_with_unknown_email_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": _unique_email(), "password": "whatever123"}
    )
    assert response.status_code == 401


async def test_me_without_token_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_me_with_malformed_token_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


async def test_me_with_expired_token_returns_401(client: httpx.AsyncClient) -> None:
    email = _unique_email()
    try:
        register_response = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "correcthorse123"}
        )
        user_id = uuid.UUID(register_response.json()["id"])
        expired_token = create_access_token(user_id, expires_delta=timedelta(seconds=-1))

        response = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert response.status_code == 401
    finally:
        await _cleanup_user_by_email(email)


async def test_me_with_valid_token_returns_current_user(client: httpx.AsyncClient) -> None:
    email = _unique_email()
    try:
        await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "correcthorse123"}
        )
        login_response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "correcthorse123"}
        )
        token = login_response.json()["access_token"]

        response = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == email
        assert "password" not in body
        assert "password_hash" not in body
    finally:
        await _cleanup_user_by_email(email)


async def test_me_token_for_deleted_user_returns_401(client: httpx.AsyncClient) -> None:
    email = _unique_email()
    register_response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correcthorse123"}
    )
    user_id = uuid.UUID(register_response.json()["id"])
    token = create_access_token(user_id)

    # Delete the user out from under the token.
    await _cleanup_user_by_email(email)

    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_health_endpoint_still_accessible_without_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "pitchfight-api"}
