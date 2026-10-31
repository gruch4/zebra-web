from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Printer(TimestampMixin, Base):
    __tablename__ = "printers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=9100)
    dpi: Mapped[int] = mapped_column(Integer, default=203)
    model: Mapped[str | None] = mapped_column(String(100))
    firmware: Mapped[str | None] = mapped_column(String(100))
    is_default: Mapped[bool] = mapped_column(default=False)
    # Which groups of printer settings embedded in labels are used ("label") or replaced by
    # the printer's own configuration ("printer"); see app.zpl.printer_settings.
    label_settings: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)


class Label(TimestampMixin, Base):
    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(16))  # "zpl" | "design"
    zpl: Mapped[str] = mapped_column(Text, default="")
    design: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    width_mm: Mapped[float | None] = mapped_column(Float)
    height_mm: Mapped[float | None] = mapped_column(Float)
    dpi: Mapped[int] = mapped_column(Integer, default=203)
    variables: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_by: Mapped[str | None] = mapped_column(String(255))
    # Set when the label is managed by an external system through the API: the caller's own id
    # for it, unique per token owner. Lets the same ref update the label instead of duplicating.
    external_ref: Mapped[str | None] = mapped_column(String(255))
    external_owner: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        Index(
            "uq_labels_external_ref",
            "external_owner",
            "external_ref",
            unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
    )


class ApiToken(Base):
    """Credential for the external API. Only a hash of the token is stored."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_sub: Mapped[str] = mapped_column(String(255), index=True)
    owner_identity: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PrintBatch(Base):
    __tablename__ = "print_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    label_id: Mapped[int | None] = mapped_column(ForeignKey("labels.id", ondelete="SET NULL"))
    label_name: Mapped[str] = mapped_column(String(200), default="")
    printer_id: Mapped[int | None] = mapped_column(ForeignKey("printers.id", ondelete="SET NULL"))
    printer_name: Mapped[str] = mapped_column(String(200), default="")
    data_filename: Mapped[str] = mapped_column(String(255), default="")
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PrintJob(Base):
    __tablename__ = "print_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    printer_id: Mapped[int | None] = mapped_column(
        ForeignKey("printers.id", ondelete="SET NULL"), index=True
    )
    printer_name: Mapped[str] = mapped_column(String(200), default="")
    printer_host: Mapped[str] = mapped_column(String(255), default="")
    dpi: Mapped[int] = mapped_column(Integer, default=203)
    label_id: Mapped[int | None] = mapped_column(ForeignKey("labels.id", ondelete="SET NULL"))
    label_name: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(16))
    zpl: Mapped[str] = mapped_column(Text)
    variables: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    copies: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("print_batches.id", ondelete="SET NULL"), index=True
    )
    batch_row: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    # API jobs only: the token that sent it and the caller's Idempotency-Key (kept for sent jobs
    # so a retried request returns this job instead of printing again).
    api_token_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_tokens.id", ondelete="SET NULL")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    idempotency_hash: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index(
            "uq_print_jobs_idempotency",
            "api_token_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class UserDraft(Base):
    """Per-user work in progress, e.g. the last ZPL pasted on the Print ZPL page."""

    __tablename__ = "user_drafts"

    user_sub: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
