"""Shared fixtures: a migrated test DB and two tenants rolled back after each test."""
import os

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.auth import password_hasher
from app.db import engine, get_db
from app.main import app
from app.models import Membership, Project, Tenant, User

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
