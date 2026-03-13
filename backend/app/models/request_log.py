import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Numeric, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from ..database import Base


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    actual_cost: Mapped[float | None] = mapped_column(Numeric(10, 8))
    baseline_cost: Mapped[float | None] = mapped_column(Numeric(10, 8))
    cost_saved: Mapped[float | None] = mapped_column(Numeric(10, 8))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="success")
    prompt_hash: Mapped[str | None] = mapped_column(String(64))  # SHA256 for cache tracking
