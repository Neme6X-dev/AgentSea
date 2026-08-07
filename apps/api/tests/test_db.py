"""Tests du CRUD db.py contre le PostgreSQL portable (base sites_test)."""
from __future__ import annotations

import pytest

from app import db


@pytest.fixture
def user() -> dict:
    u = db.create_user("test@example.com", password_hash="hash123", name="Test")
    assert u is not None
    return u


class TestUserCrud:
    def test_create_and_get(self, user):
        fetched = db.get_user(user["id"])
        assert fetched["email"] == "test@example.com"
        assert fetched["id"] == user["id"]

    def test_lowercases_email(self, user):
        assert db.get_user_by_email("TEST@example.com")["id"] == user["id"]

    def test_duplicate_email_rejected(self, user):
        assert db.create_user("test@example.com") is None

    def test_oauth_lookup(self):
        u = db.create_user("gh@example.com", provider="github", github_id="12345")
        assert db.get_user_by_github_id("12345")["id"] == u["id"]
        assert db.get_user_by_github_id("nope") is None

    def test_link_github(self, user):
        db.link_github_id(user["id"], "9999")
        assert db.get_user_by_github_id("9999")["id"] == user["id"]
        assert db.get_user(user["id"])["provider"] == "github"


class TestSessionCrud:
    def test_create_session(self, user):
        sid = db.create_session(user["id"], "Restaurant", "restaurant")
        s = db.get_session(sid)
        assert s["status"] == "pending"
        assert s["steps"] == []

    def test_allocate_slug_unique(self, user):
        db.create_session(user["id"], "Café Paris", "cafe-paris")
        first = db.allocate_slug("Café Paris")
        assert first == "cafe-paris-1"
        # la session réellement créée avec le slug alloué déclenche le suffixe suivant
        db.create_session(user["id"], "Café Paris", first)
        assert db.allocate_slug("Café Paris") == "cafe-paris-2"

    def test_allocate_slug_free(self, user):
        assert db.allocate_slug("Boulangerie Neuve") == "boulangerie-neuve"

    def test_update_step_appends(self, user):
        sid = db.create_session(user["id"], "p", "p")
        db.update_step(sid, "code", "done", "v1")
        s = db.get_session(sid)
        assert len(s["steps"]) == 1
        assert s["steps"][0]["step"] == "code"
        db.update_step(sid, "deploy", "running", "")
        assert len(db.get_session(sid)["steps"]) == 2

    def test_set_session_field(self, user):
        sid = db.create_session(user["id"], "p", "p")
        db.set_session_field(sid, status="deployed", site_url="http://x")
        s = db.get_session(sid)
        assert s["status"] == "deployed"
        assert s["site_url"] == "http://x"

    def test_list_sessions_scoped(self, user):
        other = db.create_user("o@example.com")
        db.create_session(user["id"], "a", "a")
        db.create_session(user["id"], "b", "b")
        db.create_session(other["id"], "c", "c")
        mine = db.list_sessions(user["id"])
        assert {s["slug"] for s in mine} == {"a", "b"}
        assert db.list_sessions(other["id"])[0]["slug"] == "c"

    def test_get_session_by_slug(self, user):
        db.create_session(user["id"], "p", "un-slug-ok")
        assert db.get_session_by_slug("un-slug-ok") is not None
        assert db.get_session_by_slug("absent") is None


class TestArtifactCrud:
    def test_add_and_list(self, user):
        sid = db.create_session(user["id"], "p", "p")
        db.add_artifact(sid, "site", 1, {"version": 1})
        db.add_artifact(sid, "site", 2, {"version": 2})
        by_kind = db.get_artifacts(sid, "site")
        assert [a["version"] for a in by_kind] == [1, 2]

    def test_latest_version(self, user):
        sid = db.create_session(user["id"], "p", "p")
        assert db.latest_version(sid, "site") == 0
        db.add_artifact(sid, "site", 3, {"version": 3})
        db.add_artifact(sid, "site", 7, {"version": 7})
        assert db.latest_version(sid, "site") == 7

    def test_artifact_decode_payload(self, user):
        sid = db.create_session(user["id"], "p", "p")
        db.add_artifact(sid, "design_spec", 1, {"name": "A", "items": [1, 2]})
        a = db.get_artifacts(sid, "design_spec")[0]
        assert a["payload"] == {"name": "A", "items": [1, 2]}

    def test_filter_kind(self, user):
        sid = db.create_session(user["id"], "p", "p")
        db.add_artifact(sid, "site", 1, {})
        db.add_artifact(sid, "report", 1, {})
        assert len(db.get_artifacts(sid, "site")) == 1
        assert len(db.get_artifacts(sid)) == 2
    def test_rewriting_same_version_replaces_it(self, user):
        """Republier une version, ou relancer /api/agents/code, réécrit le même triplet.

        Avec un INSERT sec, la contrainte d'unicité (session, kind, version) levait une
        IntegrityError qui ressortait en HTTP 500 sur le retour arrière et sur un second
        appel de génération.
        """
        sid = db.create_session(user["id"], "p", "p")
        db.add_artifact(sid, "deploy", 1, {"version": 1, "url": "premiere"})
        db.add_artifact(sid, "deploy", 1, {"version": 1, "url": "republiee"})

        deploys = db.get_artifacts(sid, "deploy")
        assert len(deploys) == 1
        assert deploys[0]["payload"]["url"] == "republiee"

    def test_latest_artifact_follows_write_order(self, user):
        """Après un retour arrière, la version en ligne est la plus ANCIENNE.

        get_artifacts trie par numéro de version : s'y fier ferait croire que la v3
        est toujours publiée alors qu'on vient de revenir sur la v1.
        """
        sid = db.create_session(user["id"], "p", "p")
        db.add_artifact(sid, "deploy", 1, {"version": 1})
        db.add_artifact(sid, "deploy", 3, {"version": 3})
        assert db.latest_artifact(sid, "deploy")["version"] == 3

        db.add_artifact(sid, "deploy", 1, {"version": 1})  # rollback
        assert db.latest_artifact(sid, "deploy")["version"] == 1
        assert db.get_artifacts(sid, "deploy")[-1]["version"] == 3  # tri par version

    def test_latest_artifact_none_when_absent(self, user):
        sid = db.create_session(user["id"], "p", "p")
        assert db.latest_artifact(sid, "deploy") is None
