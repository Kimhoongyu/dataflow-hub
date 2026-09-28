"""Worker support: retry backoff, result files and worker heartbeats."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("result_blob_name", sa.String(500), nullable=True))
    op.create_table("worker_heartbeats",
        sa.Column("worker_id", sa.String(100), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("current_job_id", sa.Uuid(), nullable=True),
        sa.Column("processed_count", sa.Integer(), nullable=False))
    op.create_index("ix_worker_heartbeats_last_seen_at", "worker_heartbeats", ["last_seen_at"])


def downgrade():
    op.drop_table("worker_heartbeats")
    op.drop_column("jobs", "result_blob_name")
    op.drop_column("jobs", "next_attempt_at")
