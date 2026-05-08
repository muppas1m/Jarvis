"""initial schema — every custom table the app owns

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-05-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


# revision identifiers — referenced by 002_langgraph_checkpoints' down_revision
revision: str = "001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- audit_trail ----------------------------------------------------------
    op.create_table(
        "audit_trail",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=200), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("safety_level", sa.String(length=20), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_trail_executed_at", "audit_trail", ["executed_at"])
    op.create_index("ix_audit_trail_thread_id", "audit_trail", ["thread_id"])
    op.create_index("ix_audit_trail_tool_name", "audit_trail", ["tool_name"])

    # --- conversation_analytics ----------------------------------------------
    op.create_table(
        "conversation_analytics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("channel_user_id", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("total_cost_usd", sa.Float(), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversation_analytics_last_message_at", "conversation_analytics", ["last_message_at"])
    op.create_index("ix_conversation_analytics_thread_id", "conversation_analytics", ["thread_id"], unique=True)

    # --- document_chunks ------------------------------------------------------
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("contextual_summary", sa.Text(), nullable=True),
        sa.Column("content_with_context", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_chunks_doc_chunk", "document_chunks", ["document_id", "chunk_index"])
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    # HNSW index — pgvector's high-performance approximate nearest-neighbour
    # index. Without this, cosine search degrades to a full sequential scan
    # the moment we have more than a few hundred chunks.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops);"
    )

    # --- email_logs -----------------------------------------------------------
    op.create_table(
        "email_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("sender", sa.String(length=255), nullable=True),
        sa.Column("classification", sa.String(length=20), nullable=True),
        sa.Column("draft_response", sa.Text(), nullable=True),
        sa.Column("response_complexity", sa.String(length=20), nullable=True),
        sa.Column("auto_sent", sa.Boolean(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_logs_gmail_message_id", "email_logs", ["gmail_message_id"], unique=True)
    op.create_index("ix_email_logs_sender", "email_logs", ["sender"])

    # --- llm_usage_logs -------------------------------------------------------
    op.create_table(
        "llm_usage_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("langfuse_trace_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_logs_created_at", "llm_usage_logs", ["created_at"])
    op.create_index("ix_llm_usage_logs_model", "llm_usage_logs", ["model"])
    op.create_index("ix_llm_usage_logs_thread_id", "llm_usage_logs", ["thread_id"])

    # --- memory_episodes ------------------------------------------------------
    op.create_table(
        "memory_episodes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("memory_type", sa.String(length=50), nullable=False),
        sa.Column("source_thread_id", sa.String(length=255), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_episodes_active_created", "memory_episodes", ["is_active", "created_at"])
    op.create_index("ix_memory_episodes_source_thread_id", "memory_episodes", ["source_thread_id"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memory_episodes_embedding_hnsw "
        "ON memory_episodes USING hnsw (embedding vector_cosine_ops);"
    )

    # --- pending_approvals ----------------------------------------------------
    op.create_table(
        "pending_approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("interrupt_id", sa.String(length=255), nullable=False),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_via", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pending_approvals_created_at", "pending_approvals", ["created_at"])
    op.create_index("ix_pending_approvals_expires_at", "pending_approvals", ["expires_at"])
    op.create_index("ix_pending_approvals_status", "pending_approvals", ["status"])
    op.create_index("ix_pending_approvals_status_expires", "pending_approvals", ["status", "expires_at"])
    op.create_index("ix_pending_approvals_thread_id", "pending_approvals", ["thread_id"])

    # --- rate_limit_events ----------------------------------------------------
    op.create_table(
        "rate_limit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("limit_type", sa.String(length=50), nullable=False),
        sa.Column("limit_value", sa.Integer(), nullable=False),
        sa.Column("actual_value", sa.Integer(), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rate_limit_events_occurred_at", "rate_limit_events", ["occurred_at"])
    op.create_index("ix_rate_limit_events_thread_id", "rate_limit_events", ["thread_id"])

    # --- tool_embeddings ------------------------------------------------------
    op.create_table(
        "tool_embeddings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("is_always_loaded", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tool_name"),
    )
    # ToolEmbedding gets queried on every agent turn (top-k cosine for dynamic
    # tool loading), so the HNSW index is non-negotiable here.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tool_embeddings_embedding_hnsw "
        "ON tool_embeddings USING hnsw (embedding vector_cosine_ops);"
    )

    # --- tool_results ---------------------------------------------------------
    op.create_table(
        "tool_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("tool_call_id", sa.String(length=255), nullable=False),
        sa.Column("full_result", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_results_created_at", "tool_results", ["created_at"])
    op.create_index("ix_tool_results_thread_id", "tool_results", ["thread_id"])

    # --- user_profiles --------------------------------------------------------
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("always_on", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("on_demand", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
    op.drop_index("ix_tool_results_thread_id", table_name="tool_results")
    op.drop_index("ix_tool_results_created_at", table_name="tool_results")
    op.drop_table("tool_results")
    op.execute("DROP INDEX IF EXISTS ix_tool_embeddings_embedding_hnsw")
    op.drop_table("tool_embeddings")
    op.drop_index("ix_rate_limit_events_thread_id", table_name="rate_limit_events")
    op.drop_index("ix_rate_limit_events_occurred_at", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
    op.drop_index("ix_pending_approvals_thread_id", table_name="pending_approvals")
    op.drop_index("ix_pending_approvals_status_expires", table_name="pending_approvals")
    op.drop_index("ix_pending_approvals_status", table_name="pending_approvals")
    op.drop_index("ix_pending_approvals_expires_at", table_name="pending_approvals")
    op.drop_index("ix_pending_approvals_created_at", table_name="pending_approvals")
    op.drop_table("pending_approvals")
    op.execute("DROP INDEX IF EXISTS ix_memory_episodes_embedding_hnsw")
    op.drop_index("ix_memory_episodes_source_thread_id", table_name="memory_episodes")
    op.drop_index("ix_memory_episodes_active_created", table_name="memory_episodes")
    op.drop_table("memory_episodes")
    op.drop_index("ix_llm_usage_logs_thread_id", table_name="llm_usage_logs")
    op.drop_index("ix_llm_usage_logs_model", table_name="llm_usage_logs")
    op.drop_index("ix_llm_usage_logs_created_at", table_name="llm_usage_logs")
    op.drop_table("llm_usage_logs")
    op.drop_index("ix_email_logs_sender", table_name="email_logs")
    op.drop_index("ix_email_logs_gmail_message_id", table_name="email_logs")
    op.drop_table("email_logs")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_doc_chunk", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_conversation_analytics_thread_id", table_name="conversation_analytics")
    op.drop_index("ix_conversation_analytics_last_message_at", table_name="conversation_analytics")
    op.drop_table("conversation_analytics")
    op.drop_index("ix_audit_trail_tool_name", table_name="audit_trail")
    op.drop_index("ix_audit_trail_thread_id", table_name="audit_trail")
    op.drop_index("ix_audit_trail_executed_at", table_name="audit_trail")
    op.drop_table("audit_trail")
