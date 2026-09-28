import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app import jobs as jobs_module
from app import main as main_module
from app.main import app
from app.models import Job, JobEvent, Project, UploadedFile
from app.storage import StorageUnavailable, get_storage
from conftest import login

CSV = b"id,amount\n1,10\n2,20\n"


class FakeStorage:
    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.fail = False

    def upload(self, name, data, content_type="text/csv"):
        if self.fail:
            raise StorageUnavailable
        assert name not in self.blobs
        self.blobs[name] = data

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


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_upload_stores_blob_and_queues_job(env):
    client, db, tenants, projects, storage = env
    result = client.post(f"/api/tenants/{tenants[0].id}/projects/{projects[0].id}/jobs",
                         files={"file": ("C:\\fakepath\\orders.csv", CSV, "text/csv")},
                         data={"job_type": "cleansing", "notes": "  first run  "},
                         headers={"x-request-id": "trace-123"})
    assert result.status_code == 201
    job = result.json()
    assert job["status"] == "queued"
    assert job["job_type"] == "cleansing"
    assert job["notes"] == "first run"
    assert job["project"] == {"id": str(projects[0].id), "name": projects[0].name}
    assert job["file"]["original_name"] == "orders.csv"
    assert job["file"]["size_bytes"] == len(CSV)
    assert result.headers["x-request-id"] == "trace-123"

    [(blob_name, data)] = storage.blobs.items()
    assert data == CSV
    # Storage key is tenant/project scoped and ignores the user-supplied name.
    assert blob_name.startswith(f"{tenants[0].id}/{projects[0].id}/") and "orders" not in blob_name
    row = db.get(Job, job["id"])
    assert row.request_id == "trace-123"
    assert db.get(UploadedFile, row.file_id).blob_name == blob_name
    [event] = db.scalars(select(JobEvent).where(JobEvent.job_id == row.id)).all()
    assert (event.from_status, event.to_status) == (None, "queued")


def test_list_filters_and_detail_history(env):
    client, _, tenants, projects, _ = env
    first = upload(client, tenants[0], projects[0], "a.csv").json()
    upload(client, tenants[0], projects[0], "b.csv", job_type="aggregation")
    path = f"/api/tenants/{tenants[0].id}/jobs"
    page = client.get(path).json()
    assert page["total"] == 2
    assert page["items"][0]["file"]["original_name"] == "b.csv"
    assert client.get(f"{path}?project_id={projects[0].id}").json()["total"] == 2
    assert client.get(f"{path}?status=queued").json()["total"] == 2
    assert client.get(f"{path}?status=failed").json()["total"] == 0
    assert client.get(f"{path}?status=unknown").status_code == 422
    assert len(client.get(f"{path}?limit=1").json()["items"]) == 1
    detail = client.get(f"{path}/{first['id']}").json()
    assert detail["file"]["original_name"] == "a.csv"
    assert [(e["from_status"], e["to_status"]) for e in detail["events"]] == [(None, "queued")]


def test_tenant_isolation_for_uploads_and_jobs(env):
    client, db, tenants, projects, storage = env
    a, b = tenants
    job = upload(client, a, projects[0]).json()
    # Another tenant's project, whether addressed through our tenant or theirs.
    assert upload(client, a, projects[1]).status_code == 404
    assert upload(client, b, projects[1]).status_code == 404
    assert client.get(f"/api/tenants/{a.id}/jobs?project_id={projects[1].id}").json()["total"] == 0
    assert len(storage.blobs) == 1
    login(client, "b@test.local")
    assert client.get(f"/api/tenants/{a.id}/jobs").status_code == 404
    assert client.get(f"/api/tenants/{a.id}/jobs/{job['id']}").status_code == 404
    assert client.get(f"/api/tenants/{b.id}/jobs/{job['id']}").status_code == 404
    assert client.get(f"/api/tenants/{b.id}/jobs").json()["total"] == 0
    assert count(db, Job) == 1


@pytest.mark.parametrize("name, content, job_type, status", [
    ("orders.txt", CSV, "validation", 422),
    (".csv", CSV, "validation", 422),
    ("empty.csv", b"", "validation", 422),
    ("blank.csv", b" \n\n", "validation", 422),
    ("cp949.csv", "이름\n".encode("cp949"), "validation", 422),
    ("binary.csv", b"id\x00,amount\n", "validation", 422),
    ("orders.csv", CSV, "unknown", 422),
])
def test_rejected_uploads_store_nothing(env, name, content, job_type, status):
    client, db, tenants, projects, storage = env
    assert upload(client, tenants[0], projects[0], name, content, job_type).status_code == status
    assert storage.blobs == {}
    assert count(db, Job) == count(db, UploadedFile) == 0


def test_utf8_bom_is_accepted(env):
    client, _, tenants, projects, _ = env
    assert upload(client, tenants[0], projects[0], content="\ufeff이름,값\n가,1\n".encode("utf-8")).status_code == 201


def test_size_limits(env, monkeypatch):
    client, db, tenants, projects, storage = env
    monkeypatch.setattr(jobs_module, "MAX_UPLOAD_BYTES", len(CSV) - 1)
    assert upload(client, tenants[0], projects[0]).status_code == 413
    # The middleware rejects on Content-Length before the body is parsed.
    monkeypatch.setattr(main_module, "MAX_REQUEST_BYTES", 100)
    assert upload(client, tenants[0], projects[0], content=b"a" * 200).status_code == 413
    assert storage.blobs == {}
    assert count(db, Job) == 0


def test_storage_outage_returns_503_without_db_rows(env):
    client, db, tenants, projects, storage = env
    storage.fail = True
    result = upload(client, tenants[0], projects[0])
    assert result.status_code == 503
    assert "저장소" in result.json()["detail"]
    assert count(db, Job) == count(db, UploadedFile) == 0


def test_db_failure_removes_uploaded_blob(env, monkeypatch):
    client, db, tenants, projects, storage = env
    def broken_commit():
        raise OperationalError("COMMIT", {}, Exception("db down"))
    monkeypatch.setattr(db, "commit", broken_commit)
    with pytest.raises(OperationalError):
        upload(client, tenants[0], projects[0])
    assert storage.blobs == {}


def test_upload_requires_login_and_allowed_origin(env):
    client, _, tenants, projects, storage = env
    client.post("/api/auth/logout")
    assert upload(client, tenants[0], projects[0]).status_code == 401
    login(client)
    del client.headers["origin"]
    assert upload(client, tenants[0], projects[0]).status_code == 403
    assert storage.blobs == {}
