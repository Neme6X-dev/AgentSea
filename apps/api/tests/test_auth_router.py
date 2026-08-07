"""Tests du router /api/auth (register/login/google/github) via TestClient, dépendances mockées."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)
BASE = "/api/auth"
USER = {"id": 7, "email": "flo@example.com", "name": "Flo", "provider": "local"}


class TestRegister:
    def test_register_creates_user(self):
        with patch("app.routers.auth.db.get_user_by_email", return_value=None), patch(
            "app.routers.auth.db.create_user", return_value=USER
        ), patch("app.routers.auth.hash_password", return_value="h"), patch(
            "app.routers.auth.create_access_token", return_value="tok"
        ):
            r = client.post(f"{BASE}/register", json={"email": "flo@example.com", "password": "s3cret!!"})
        assert r.status_code == 201
        assert r.json()["access_token"] == "tok"
        assert r.json()["user"]["email"] == "flo@example.com"

    def test_register_conflict(self):
        existing = dict(USER)
        with patch("app.routers.auth.db.get_user_by_email", return_value=existing):
            r = client.post(f"{BASE}/register", json={"email": "flo@example.com", "password": "xlongpass"})
        assert r.status_code == 409

    def test_register_weak_password_rejected(self):
        r = client.post(f"{BASE}/register", json={"email": "a@b.fr", "password": "abc"})
        assert r.status_code == 422


class TestLogin:
    def test_login_ok(self):
        user = dict(USER, password_hash="hash")
        with patch("app.routers.auth.db.get_user_by_email", return_value=user), patch(
            "app.routers.auth.verify_password", return_value=True
        ), patch("app.routers.auth.create_access_token", return_value="tok"), patch(
            "app.routers.auth.reset_failures"
        ):
            r = client.post(f"{BASE}/login", json={"email": "flo@example.com", "password": "bon"})
        assert r.status_code == 200
        assert r.json()["access_token"] == "tok"

    def test_login_wrong_password(self):
        user = dict(USER, password_hash="hash")
        with patch("app.routers.auth.db.get_user_by_email", return_value=user), patch(
            "app.routers.auth.verify_password", return_value=False
        ), patch("app.routers.auth.record_failure"):
            r = client.post(f"{BASE}/login", json={"email": "flo@example.com", "password": "mauvais"})
        assert r.status_code == 401

    def test_login_unknown_user(self):
        with patch("app.routers.auth.db.get_user_by_email", return_value=None):
            r = client.post(f"{BASE}/login", json={"email": "nobody@example.com", "password": "x"})
        assert r.status_code == 401


class TestGoogle:
    def test_google_new_user(self):
        info = {"sub": "gsub1", "email": "g@example.com", "name": "G"}
        with patch("app.routers.auth.verify_google_id_token", return_value=info), patch(
            "app.routers.auth.db.get_user_by_google_sub", return_value=None
        ), patch("app.routers.auth.db.get_user_by_email", return_value=None), patch(
            "app.routers.auth.db.create_user", return_value=dict(USER, email="g@example.com")
        ), patch("app.routers.auth.create_access_token", return_value="tok"):
            r = client.post(f"{BASE}/google", json={"id_token": "x" * 40})
        assert r.status_code == 200

    def test_google_links_existing_email(self):
        info = {"sub": "gsub2", "email": "flo@example.com", "name": "F"}
        with patch("app.routers.auth.verify_google_id_token", return_value=info), patch(
            "app.routers.auth.db.get_user_by_google_sub", return_value=None
        ), patch("app.routers.auth.db.get_user_by_email", return_value=dict(USER)), patch(
            "app.routers.auth.db.link_google_sub"
        ), patch("app.routers.auth.create_access_token", return_value="tok"):
            r = client.post(f"{BASE}/google", json={"id_token": "x" * 40})
        assert r.status_code == 200


class TestGithub:
    def test_github_new_user(self):
        info = {"id": "997", "login": "flodesign", "email": "dev@example.com"}
        with patch("app.routers.auth.exchange_github_code", return_value="gho_token"), patch(
            "app.routers.auth.get_github_user", return_value=info
        ), patch("app.routers.auth.db.get_user_by_github_id", return_value=None), patch(
            "app.routers.auth.db.get_user_by_email", return_value=None
        ), patch("app.routers.auth.db.create_user", return_value=dict(USER, email="flo@example.com")), patch(
            "app.routers.auth.create_access_token", return_value="tok"
        ):
            r = client.post(f"{BASE}/github", json={"code": "code987"})
        assert r.status_code == 200
        assert r.json()["access_token"] == "tok"

    def test_github_bad_code(self):
        from fastapi import HTTPException
        with patch(
            "app.routers.auth.exchange_github_code",
            side_effect=HTTPException(status_code=401, detail="Code invalide"),
        ):
            r = client.post(f"{BASE}/github", json={"code": "bad"})
        assert r.status_code == 401


class TestMe:
    auth = {"Authorization": "Bearer tok"}

    def test_me_ok(self):
        from app.security import current_user
        app.dependency_overrides[current_user] = lambda: USER
        try:
            r = client.get(f"{BASE}/me", headers=self.auth)
        finally:
            app.dependency_overrides.pop(current_user, None)
        assert r.status_code == 200
        assert r.json()["email"] == "flo@example.com"

    def test_me_unauthorized(self):
        r = client.get(f"{BASE}/me")
        assert r.status_code == 401