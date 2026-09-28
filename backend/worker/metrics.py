"""Worker metrics, served on WORKER_METRICS_PORT (default 9100) for Prometheus.

Queue gauges are global (all tenants) and every worker reports the same value, so dashboards
should aggregate them with max(), not sum().
"""
from prometheus_client import Counter, Gauge, Histogram

JOBS_FINISHED = Counter("dataflow_jobs_finished_total", "Job attempts finished by outcome",
                        ["job_type", "outcome"])  # outcome: completed | failed | retried
JOB_DURATION = Histogram("dataflow_job_duration_seconds", "Time spent processing one job attempt", ["job_type"],
                         buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60))
ROWS_PROCESSED = Counter("dataflow_rows_processed_total", "CSV data rows read by completed jobs", ["job_type"])
JOB_ERRORS = Counter("dataflow_job_errors_total", "Failed or retried attempts by error code", ["error_code"])
JOBS_RECOVERED = Counter("dataflow_jobs_recovered_total", "Processing jobs taken back from unresponsive workers")
QUEUE_DEPTH = Gauge("dataflow_queue_depth", "Queued jobs across all tenants")
OLDEST_QUEUED = Gauge("dataflow_oldest_queued_seconds", "Age of the oldest queued job (0 when the queue is empty)")
PROCESSING = Gauge("dataflow_jobs_processing", "Jobs currently in processing across all tenants")
