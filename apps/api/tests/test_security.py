"""Tests de security.py : argon2, JWT, rate-limit, GitHub OAuth (httpx mocké)."""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from app.security import (
    create_access_token,
    decode_token,
    exchange_github_code,
    get_github_user,
    hash_password,
    verify_password,
)


class TestPassword:
    def test_hash_and_verify(self):
        h = hash_password("motdepasse123!")
        assert h != "motdepasse123!"
        assert verify_password("motdepasse123!", h)

    def test_verify_wrong_password(self):
        h = hash_password("bonmotdepasse")
        assert not verify_password("mauvais", h)


class TestJwt:
    def test_roundtrip(self):
        token = create_access_token(42)
        payload = decode_token(token)
        assert payload["sub"] == "42"

    def test_expired_token_rejected(self):
        import jwt
        from app.config import settings
        expired = jwt.encode({"sub": "1", "exp": 0}, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(HTTPException) as exc:
            decode_token(expired)
        assert exc.value.status_code == 401

    def test_invalid_token_rejected(self):
        with pytest.raises(HTTPException) as exc:
            decode_token("not-a-jwt")
        assert exc.value.status_code == 401


class TestRateLimit:
    """Le compteur de tentatives vit en base, plus en mémoire.

    La version en mémoire ne protégeait qu'un processus : derrière plusieurs workers
    uvicorn la limite était multipliée d'autant, et un redémarrage la remettait à
    zéro. Ces tests vérifient donc le comportement observable — bloqué / passant —
    sans supposer où le compteur est rangé.
    """

    def _reset(self):
        from app import db
        with db.session_scope() as s:
            s.query(db.AuthAttempt).delete()

    def test_blocked_after_max_attempts(self):
        self._reset()
        from app import security
        from app.config import settings
        key = "login:a@b.fr:ip"
        for _ in range(settings.auth_max_attempts):
            security.record_failure(key)
        with pytest.raises(HTTPException) as exc:
            security.check_rate_limit(key)
        assert exc.value.status_code == 429

    def test_allowed_below_threshold(self):
        self._reset()
        from app import security
        security.record_failure("login:x:ip")
        security.check_rate_limit("login:x:ip")  # ne doit pas lever

    def test_reset_clears(self):
        self._reset()
        from app import security
        key = "login:c:ip"
        security.record_failure(key)
        security.reset_failures(key)
        security.check_rate_limit(key)


class TestGithubOAuth:
    @pytest.fixture(autouse=True)
    def _configure(self):
        from app.config import Settings
        import dataclasses
        fake = dataclasses.replace(
            Settings(),
            github_client_id="test-client",
            github_client_secret="test-secret",
        )
        with patch("app.security.settings", fake):
            yield fake

    def test_exchange_code_success(self):
        with patch("app.security.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json={"access_token": "gho_abc"})
            token = exchange_github_code("code123")
            assert token == "gho_abc"
            sent = mock_post.call_args
            assert sent.kwargs["data"]["client_id"] == "test-client"

    def test_exchange_code_error(self):
        with patch("app.security.httpx.post") as mock_post:
            mock_post.return_value = httpx.Response(200, json={"error": "bad_verification_code"})
            with pytest.raises(HTTPException) as exc:
                exchange_github_code("mauvais")
            assert exc.value.status_code == 401

    def test_get_github_user_success(self):
        with patch("app.security.httpx.get") as mock_get:
            mock_get.return_value = httpx.Response(
                200,
                json={"id": 1234, "login": "flo", "name": "Flo", "email": "flo@example.com"},
            )
            info = get_github_user("gho_abc")
            assert info["id"] == "1234"
            assert info["email"] == "flo@example.com"

    def test_get_github_user_http_error(self):
        with patch("app.security.httpx.get") as mock_get:
            mock_get.return_value = httpx.Response(401, json={"message": "Bad credentials"})
            with pytest.raises(HTTPException) as exc:
                get_github_user("bad")
            assert exc.value.status_code == 401

    def test_get_github_user_missing_id(self):
        with patch("app.security.httpx.get") as mock_get:
            mock_get.return_value = httpx.Response(200, json={"login": "x"})
            with pytest.raises(HTTPException) as exc:
                get_github_user("token")
            assert exc.value.status_code == 401
