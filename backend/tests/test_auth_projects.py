from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import COOKIE, hash_token, password_hasher
from app.db import engine, get_db
from app.main import app
from app.models import LoginSession, Membership, Project, Tenant, User

ORIGIN = {"origin": "http://localhost:5173"}
PASSWORD = "Test-password-2026!"


@pytest.fixture(scope="session", autouse=True)
def migrate():
    assert os.environ["POSTGRES_DB"].endswith("_test"), "Use a dedicated test database"
    command.upgrade(Config("alembic.ini"), "head")
    command.check(Config("alembic.ini"))


@pytest.fixture()
def setup():
    with engine.connect() as connection:
        transaction = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        tenants = [Tenant(name="A"), Tenant(name="B")]
        users = [User(email=f"{name}@test.local", name=name, password_hash=password_hasher.hash(PASSWORD)) for name in ("a", "b")]
        db.add_all(tenants + users)
        db.flush()
        for user, tenant in zip(users, tenants):
            db.add(Membership(user_id=user.id, tenant_id=tenant.id))
            db.add(Project(tenant_id=tenant.id, name=f"{tenant.name} private", description="test"))
        db.commit()
        def override_db():
            yield db
        app.dependency_overrides[get_db] = override_db
        with TestClient(app, headers=ORIGIN) as client:
            yield client, db, tenants, users
        app.dependency_overrides.clear()
        db.close()
        transaction.rollback()


def login(client, email="a@test.local", password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_login_logout_and_cookie_replay(setup):
    client, db, tenants, _ = setup
    assert client.get("/api/auth/me").status_code == 401
    assert client.get(f"/api/tenants/{tenants[0].id}/projects").status_code == 401
    assert login(client, password="wrong").status_code == 401
    assert login(client, email="missing@test.local").status_code == 401
    result = login(client)
    assert result.status_code == 200
    assert "password_hash" not in result.text
    assert "HttpOnly" in result.headers["set-cookie"]
    assert "SameSite=lax" in result.headers["set-cookie"]
    token = client.cookies.get(COOKIE)
    assert db.get(LoginSession, hash_token(token)) is not None
    assert client.get("/api/auth/me").json()["email"] == "a@test.local"
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set(COOKIE, token, path="/api")
    assert client.get("/api/auth/me").status_code == 401


def test_tenant_isolation_and_persistence(setup):
    client, db, tenants, _ = setup
    a, b = tenants
    login(client)
    path = f"/api/tenants/{a.id}/projects"
    other = f"/api/tenants/{b.id}/projects"
    b_project = db.scalar(select(Project).where(Project.tenant_id == b.id))
    assert client.get(other).status_code == 404
    assert client.post(other, json={"name": "Attack"}).status_code == 404
    assert client.get(f"{path}/{b_project.id}").status_code == 404
    assert client.get(f"{other}/{b_project.id}").status_code == 404
    assert client.post(path, json={"name": "Spoof", "tenant_id": str(b.id)}).status_code == 422
    assert client.post(path, json={"name": "   "}).status_code == 422
    created = client.post(path, json={"name": " A new ", "description": " saved "})
    assert created.status_code == 201
    project = created.json()
    assert project["name"] == "A new"
    assert project["tenant_id"] == str(a.id)
    assert client.post(path, json={"name": "A new"}).status_code == 409
    assert client.get(path).json()["total"] == 2
    assert len(client.get(path + "?limit=1&offset=1").json()["items"]) == 1
    client.post("/api/auth/logout")
    login(client)
    assert client.get(f"{path}/{project['id']}").json()["description"] == "saved"
    login(client, "b@test.local")
    assert client.get(path).status_code == 404
    assert client.get(other).json()["total"] == 1
    assert client.post(other, json={"name": "A new"}).status_code == 201


@pytest.mark.parametrize("origin", [None, "https://evil.example", "null"])
def test_csrf_rejects_login_and_writes(setup, origin):
    client, _, tenants, _ = setup
    login(client)
    if origin is None:
        del client.headers["origin"]
    else:
        client.headers["origin"] = origin
    assert login(client).status_code == 403
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post(f"/api/tenants/{tenants[0].id}/projects", json={"name": "Blocked"}).status_code == 403


def test_expired_and_rotated_sessions(setup):
    client, db, _, _ = setup
    login(client)
    old = client.cookies.get(COOKIE)
    login(client)
    assert db.get(LoginSession, hash_token(old)) is None
    session = db.get(LoginSession, hash_token(client.cookies.get(COOKIE)))
    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_revoked_membership_and_invalid_ids(setup):
    client, db, tenants, users = setup
    login(client)
    assert client.get(f"/api/tenants/{uuid4()}/projects").status_code == 404
    assert client.get("/api/tenants/not-a-uuid/projects").status_code == 422
    db.delete(db.get(Membership, (users[0].id, tenants[0].id)))
    db.commit()
    assert client.get(f"/api/tenants/{tenants[0].id}/projects").status_code == 404
    assert client.get("/api/auth/me").json()["tenants"] == []

def test_manage_user_changes_credentials_and_preserves_projects(setup):
    from app.manage_user import update_user
    client, db, tenants, users = setup
    login(client)
    original_id = users[0].id
    assert update_user(db, "a@test.local", email=" Updated@Test.local ", name=" New Name ", password="New-password-2026!")
    assert client.get("/api/auth/me").status_code == 401
    assert login(client).status_code == 401
    assert login(client, "updated@test.local", PASSWORD).status_code == 401
    result = login(client, "updated@test.local", "New-password-2026!")
    assert result.status_code == 200
    assert result.json()["id"] == str(original_id)
    assert result.json()["name"] == "New Name"
    assert client.get(f"/api/tenants/{tenants[0].id}/projects").json()["total"] == 1
    assert db.get(User, original_id).password_hash != "New-password-2026!"


def test_manage_user_duplicate_email_rolls_back_everything(setup):
    from app.manage_user import update_user
    client, db, _, users = setup
    login(client)
    with pytest.raises(ValueError, match="이미 사용"):
        update_user(db, "a@test.local", email="b@test.local", name="Wrong", password="New-password-2026!")
    assert db.get(User, users[0].id).name == "a"
    assert client.get("/api/auth/me").status_code == 200
    assert login(client).status_code == 200


@pytest.mark.parametrize("changes", [{"email": "invalid"}, {"name": "  "}, {"password": "short"}, {"password": " " * 12}])
def test_manage_user_invalid_input(setup, changes):
    from app.manage_user import update_user
    client, db, _, _ = setup
    with pytest.raises(ValueError):
        update_user(db, "a@test.local", **changes)
    assert login(client).status_code == 200


def test_manage_user_noop_and_missing_user(setup):
    from app.manage_user import update_user
    client, db, _, _ = setup
    login(client)
    assert update_user(db, "a@test.local") is False
    assert client.get("/api/auth/me").status_code == 200
    with pytest.raises(ValueError, match="계정이 없습니다"):
        update_user(db, "missing@test.local", name="Nobody")


def test_manage_user_password_confirmation_does_not_save(setup, monkeypatch):
    from app import manage_user
    client, _, _, _ = setup
    monkeypatch.setattr("sys.argv", ["manage_user", "--email", "a@test.local"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    inputs = iter(["new@test.local", "Changed", "y"])
    passwords = iter(["New-password-2026!", "different-password"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(manage_user, "getpass", lambda _: next(passwords))
    # Use the fixture session, without closing it inside the CLI context.
    from contextlib import nullcontext
    monkeypatch.setattr(manage_user, "Session", lambda _: nullcontext(setup[1]))
    assert manage_user.main() == 1
    assert login(client).status_code == 200
