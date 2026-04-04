"""initial_schema

Revision ID: 6462f591b285
Revises:
Create Date: 2026-04-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "6462f591b285"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"])
    op.create_index(op.f("ix_users_role"), "users", ["role"])

    # --- contractors ---
    op.create_table(
        "contractors",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nip", sa.String(32), nullable=False),
        sa.Column("regon", sa.String(32), nullable=True),
        sa.Column("krs", sa.String(32), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("legal_form", sa.String(128), nullable=True),
        sa.Column("street", sa.String(255), nullable=True),
        sa.Column("building_no", sa.String(32), nullable=True),
        sa.Column("apartment_no", sa.String(32), nullable=True),
        sa.Column("postal_code", sa.String(32), nullable=True),
        sa.Column("city", sa.String(128), nullable=True),
        sa.Column("voivodeship", sa.String(128), nullable=True),
        sa.Column("county", sa.String(128), nullable=True),
        sa.Column("commune", sa.String(128), nullable=True),
        sa.Column("country", sa.String(64), nullable=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cache_valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lookup_last_status", sa.String(64), nullable=True),
        sa.Column("lookup_last_error", sa.String(512), nullable=True),
        sa.Column("raw_payload_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contractors")),
        sa.UniqueConstraint("nip", name=op.f("uq_contractors_nip")),
    )
    op.create_index(op.f("ix_contractors_nip"), "contractors", ["nip"])

    # --- contractor_overrides ---
    op.create_table(
        "contractor_overrides",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("contractor_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("legal_form", sa.String(128), nullable=True),
        sa.Column("street", sa.String(255), nullable=True),
        sa.Column("building_no", sa.String(32), nullable=True),
        sa.Column("apartment_no", sa.String(32), nullable=True),
        sa.Column("postal_code", sa.String(32), nullable=True),
        sa.Column("city", sa.String(128), nullable=True),
        sa.Column("county", sa.String(128), nullable=True),
        sa.Column("commune", sa.String(128), nullable=True),
        sa.Column("voivodeship", sa.String(128), nullable=True),
        sa.Column("override_reason", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contractor_overrides")),
        sa.ForeignKeyConstraint(["contractor_id"], ["contractors.id"], name=op.f("fk_contractor_overrides_contractor_id_contractors")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_contractor_overrides_created_by_users")),
    )
    op.create_index(op.f("ix_contractor_overrides_contractor_id"), "contractor_overrides", ["contractor_id"])
    op.create_index(
        "uq_contractors_active_override",
        "contractor_overrides",
        ["contractor_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )

    # --- invoices ---
    op.create_table(
        "invoices",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("number_local", sa.String(128), nullable=True),
        sa.Column("seller_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("seller_snapshot_json", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("buyer_snapshot_json", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("totals_json", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("ksef_payload_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("validation_status", sa.String(64), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("sale_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default=sa.text("'PLN'")),
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_invoices_created_by_users")),
    )
    op.create_index(op.f("ix_invoices_number_local"), "invoices", ["number_local"])
    op.create_index(op.f("ix_invoices_status"), "invoices", ["status"])

    # --- invoice_items ---
    op.create_table(
        "invoice_items",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("invoice_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("unit_price_net", sa.Numeric(18, 2), nullable=False),
        sa.Column("vat_rate", sa.Numeric(5, 2), nullable=False),
        sa.Column("net_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("vat_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_items")),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name=op.f("fk_invoice_items_invoice_id_invoices")),
    )
    op.create_index(op.f("ix_invoice_items_invoice_id"), "invoice_items", ["invoice_id"])

    # --- transmissions ---
    op.create_table(
        "transmissions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("invoice_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(64), nullable=False, server_default=sa.text("'ksef'")),
        sa.Column("operation_type", sa.String(64), nullable=False, server_default=sa.text("'invoice_submit'")),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("external_reference", sa.String(255), nullable=True),
        sa.Column("ksef_reference_number", sa.String(255), nullable=True),
        sa.Column("request_payload_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("response_payload_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transmissions")),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name=op.f("fk_transmissions_invoice_id_invoices")),
    )
    op.create_index(op.f("ix_transmissions_invoice_id"), "transmissions", ["invoice_id"])
    op.create_index(op.f("ix_transmissions_status"), "transmissions", ["status"])
    op.create_index(op.f("ix_transmissions_idempotency_key"), "transmissions", ["idempotency_key"])
    op.create_index(op.f("ix_transmissions_external_reference"), "transmissions", ["external_reference"])
    op.create_index("ix_transmissions_invoice_status", "transmissions", ["invoice_id", "status"])

    # --- background_jobs ---
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_type", sa.String(128), nullable=False),
        sa.Column("payload_json", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(64), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(128), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("last_error", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_background_jobs")),
    )
    op.create_index(op.f("ix_background_jobs_job_type"), "background_jobs", ["job_type"])
    op.create_index(op.f("ix_background_jobs_status"), "background_jobs", ["status"])
    op.create_index(op.f("ix_background_jobs_available_at"), "background_jobs", ["available_at"])
    op.create_index("ix_background_jobs_status_available_at", "background_jobs", ["status", "available_at"])

    # --- ksef_sessions ---
    op.create_table(
        "ksef_sessions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("auth_method", sa.String(64), nullable=False),
        sa.Column("session_reference", sa.String(255), nullable=True),
        sa.Column("token_metadata_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ksef_sessions")),
    )
    op.create_index(op.f("ix_ksef_sessions_environment"), "ksef_sessions", ["environment"])
    op.create_index(op.f("ix_ksef_sessions_session_reference"), "ksef_sessions", ["session_reference"])
    op.create_index(op.f("ix_ksef_sessions_status"), "ksef_sessions", ["status"])

    # --- audit_logs ---
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(64), nullable=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(128), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("before_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("after_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("metadata_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_audit_logs_actor_user_id_users")),
    )
    op.create_index(op.f("ix_audit_logs_event_type"), "audit_logs", ["event_type"])
    op.create_index(op.f("ix_audit_logs_entity_type"), "audit_logs", ["entity_type"])
    op.create_index(op.f("ix_audit_logs_entity_id"), "audit_logs", ["entity_id"])
    op.create_index(op.f("ix_audit_logs_request_id"), "audit_logs", ["request_id"])

    # --- idempotency_keys ---
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(255), nullable=True),
        sa.Column("entity_type", sa.String(128), nullable=True),
        sa.Column("entity_id", sa.String(128), nullable=True),
        sa.Column("response_snapshot_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(64), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_keys")),
        sa.UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_scope_key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("audit_logs")
    op.drop_table("ksef_sessions")
    op.drop_table("background_jobs")
    op.drop_table("transmissions")
    op.drop_table("invoice_items")
    op.drop_table("invoices")
    op.drop_table("contractor_overrides")
    op.drop_table("contractors")
    op.drop_table("users")
