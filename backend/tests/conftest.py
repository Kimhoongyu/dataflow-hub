"""Shared fixtures: a migrated test DB and two tenants rolled back after each test."""
import os

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import password_hasher
from app.db import engine, get_db
from app.main import app
from app.models import Membership, Project, Tenant, User
from app.storage import BlobNotFound, StorageUnavailable, get_storage

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


CSV = b"id,amount\n1,10\n2,20\n"


class FakeStorage:
    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.fail = False

    def upload(self, name, data, content_type="text/csv", overwrite=False):
        if self.fail:
            raise StorageUnavailable
        assert overwrite or name not in self.blobs
        self.blobs[name] = data

    def download(self, name):
        if self.fail:
            raise StorageUnavailable
        if name not in self.blobs:
            raise BlobNotFound(name)
        return self.blobs[name]

    def delete(self, name):
        self.blobs.pop(name, None)

    def check(self):
        if self.fail:
            raise StorageUnavailable


@pytest.fixture()
def env(setup):
    client, db, tenants, users = setup
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    projects = [db.scalar(select(Project).where(Project.tenant_id == t.id)) for t in tenants]
    login(client)
    return client, db, tenants, projects, storage


def upload(client, tenant, project, name="orders.csv", content=CSV, job_type="validation", **kwargs):
    return client.post(f"/api/tenants/{tenant.id}/projects/{project.id}/jobs",
                       files={"file": (name, content, "text/csv")}, data={"job_type": job_type, **kwargs})
