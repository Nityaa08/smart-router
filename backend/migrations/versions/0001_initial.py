"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-09

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "request_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("difficulty", sa.String(20), nullable=False),
        sa.Column("model_used", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("actual_cost", sa.Numeric(10, 8)),
        sa.Column("baseline_cost", sa.Numeric(10, 8)),
        sa.Column("cost_saved", sa.Numeric(10, 8)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("status", sa.String(20), server_default="success"),
        sa.Column("prompt_hash", sa.String(64)),
    )
    op.create_index("ix_request_logs_difficulty", "request_logs", ["difficulty"])
    op.create_index("ix_request_logs_created_at", "request_logs", ["created_at"])
    op.create_index("ix_request_logs_prompt_hash", "request_logs", ["prompt_hash"])


def downgrade() -> None:
    op.drop_table("request_logs")
