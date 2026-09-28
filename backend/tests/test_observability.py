import io
import json
import logging

from prometheus_client import REGISTRY

from app.observability import JsonFormatter, request_id_var
from conftest import upload
from worker import main as worker


def sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def capture(logger_name):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter("test"))
    logging.getLogger(logger_name).addHandler(handler)
    return stream, lambda: logging.getLogger(logger_name).removeHandler(handler)


def lines(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_json_formatter_adds_context_and_extra_fields():
    stream, done = capture("test.json")
    token = request_id_var.set("req-1")
    try:
        logging.getLogger("test.json").warning("thing_happened", extra={"job_id": "j1", "count": 3, "note": "한글"})
    finally:
        request_id_var.reset(token)
        done()
    [entry] = lines(stream)
    assert entry["event"] == "thing_happened" and entry["level"] == "warning" and entry["service"] == "test"
    assert (entry["request_id"], entry["job_id"], entry["count"], entry["note"]) == ("req-1", "j1", 3, "한글")
    assert "args" not in entry and "msg" not in entry


def test_http_metrics_use_route_templates(env):
    client, _, tenants, projects, _ = env
    route = "/api/tenants/{tenant_id}/projects/{project_id}/jobs"
    before = sample("http_requests_total", method="POST", route=route, status="201")
    uploads_before = sample("dataflow_uploads_total", job_type="validation")
    assert upload(client, tenants[0], projects[0]).status_code == 201
    assert sample("http_requests_total", method="POST", route=route, status="201") == before + 1
    assert sample("dataflow_uploads_total", job_type="validation") == uploads_before + 1
    body = client.get("/metrics").text
    assert str(tenants[0].id) not in body and str(projects[0].id) not in body  # no ID ever becomes a label
    rejected = sample("http_requests_total", method="POST", route="unmatched", status="403")
    del client.headers["origin"]
    upload(client, tenants[0], projects[0])
    assert sample("http_requests_total", method="POST", route="unmatched", status="403") == rejected + 1


def test_worker_metrics_and_logs_carry_the_upload_request_id(env):
    client, db, tenants, projects, storage = env
    result = client.post(f"/api/tenants/{tenants[0].id}/projects/{projects[0].id}/jobs",
                         files={"file": ("a.csv", b"id\n1\n", "text/csv")}, data={"job_type": "cleansing"},
                         headers={"x-request-id": "trace-worker-1"})
    assert result.status_code == 201
    completed = sample("dataflow_jobs_finished_total", job_type="cleansing", outcome="completed")
    rows = sample("dataflow_rows_processed_total", job_type="cleansing")
    stream, done = capture("worker")
    try:
        worker.run_once(db, storage, "w1")
    finally:
        done()
    assert sample("dataflow_jobs_finished_total", job_type="cleansing", outcome="completed") == completed + 1
    assert sample("dataflow_rows_processed_total", job_type="cleansing") == rows + 1
    finished = [e for e in lines(stream) if e["event"] == "job_finished"]
    assert finished and finished[0]["request_id"] == "trace-worker-1" and finished[0]["status"] == "completed"
    worker.update_queue_metrics(db)
    assert sample("dataflow_queue_depth") == 0
