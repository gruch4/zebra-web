"""API tokens, external label references and print idempotency keys

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_sub", sa.String(length=255), nullable=False),
        sa.Column("owner_identity", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_api_tokens_owner_sub"), "api_tokens", ["owner_sub"], unique=False)

    op.add_column("labels", sa.Column("external_ref", sa.String(length=255), nullable=True))
    op.add_column("labels", sa.Column("external_owner", sa.String(length=255), nullable=True))
    op.create_index(
        "uq_labels_external_ref",
        "labels",
        ["external_owner", "external_ref"],
        unique=True,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )

    op.add_column("print_jobs", sa.Column("api_token_id", sa.Integer(), nullable=True))
    op.add_column("print_jobs", sa.Column("idempotency_key", sa.String(length=255), nullable=True))
    op.add_column("print_jobs", sa.Column("idempotency_hash", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        "fk_print_jobs_api_token_id",
        "print_jobs",
        "api_tokens",
        ["api_token_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_print_jobs_idempotency",
        "print_jobs",
        ["api_token_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_print_jobs_idempotency", table_name="print_jobs")
    op.drop_constraint("fk_print_jobs_api_token_id", "print_jobs", type_="foreignkey")
    op.drop_column("print_jobs", "idempotency_hash")
    op.drop_column("print_jobs", "idempotency_key")
    op.drop_column("print_jobs", "api_token_id")

    op.drop_index("uq_labels_external_ref", table_name="labels")
    op.drop_column("labels", "external_owner")
    op.drop_column("labels", "external_ref")

    op.drop_index(op.f("ix_api_tokens_owner_sub"), table_name="api_tokens")
    op.drop_table("api_tokens")
