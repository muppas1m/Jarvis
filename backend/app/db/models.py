"""
ORM models — every table the application owns.

What we DON'T own:
  - LangGraph's `checkpoints`, `checkpoint_writes`, `checkpoint_blobs`,
    `checkpoint_migrations` — created by AsyncPostgresSaver.setup() inside the
    `002_langgraph_checkpoints` migration. These store the full graph state and
    message history per thread. We never read or write them directly.
  - Mem0's `mem0_memories` table — managed by the Mem0 SDK. Our `MemoryEpisode`
    table is a parallel custom-query table, not a mirror.

Naming gotcha:
  SQLAlchemy reserves `metadata` as an attribute on `DeclarativeBase`. Every
  JSON metadata column on these models is named `meta` instead.
"""
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# Embedding dim is parameterized via settings.EMBEDDING_DIMS (locked at 1024 for
# BGE-M3). Migrating to a different embedding model means updating EMBEDDING_DIMS
# AND running the re-embed script in Phase 2 Task 2.20.
EMBEDDING_DIM = settings.EMBEDDING_DIMS


# --------------------------------------------------------------------------- #
# Tier 5 — User profile (split across always-on + on-demand)                  #
# --------------------------------------------------------------------------- #
class UserProfile(Base):
    """Master's profile, split into always-on (small, every prompt) and on-demand
    (loaded only when relevant via Mem0 retrieval)."""
    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)

    # ALWAYS-ON: small dict, joined into every system prompt.
    # Example: {"timezone": "America/New_York", "language": "English",
    #           "communication_style": "Direct, brief, bullet points"}
    always_on = Column(JSONB, nullable=False, default=dict)

    # ON-DEMAND: heavier sections fetched only when relevant.
    # Example: {"relationships": {...}, "routines": {...}, "news_topics": [...],
    #           "preferences_long": {...}}
    on_demand = Column(JSONB, nullable=False, default=dict)

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# --------------------------------------------------------------------------- #
# Cross-thread analytics — NOT the source of truth for messages               #
# --------------------------------------------------------------------------- #
class ConversationAnalytics(Base):
    """Dashboard-facing rollup per thread. LangGraph checkpoints own the actual
    message history; this table holds metadata for reporting + filtering."""
    __tablename__ = "conversation_analytics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(String(255), unique=True, nullable=False, index=True)
    platform = Column(String(50), nullable=False)             # "telegram", "whatsapp", "web"
    channel_user_id = Column(String(255), nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_message_at = Column(DateTime(timezone=True), nullable=True, index=True)
    message_count = Column(Integer, default=0, nullable=False)
    summary = Column(Text, nullable=True)
    total_cost_usd = Column(Float, default=0.0, nullable=False)
    meta = Column(JSONB, nullable=False, default=dict)


# --------------------------------------------------------------------------- #
# Tier 3 — Episodic memory (parallel to Mem0's own table)                     #
# --------------------------------------------------------------------------- #
class MemoryEpisode(Base):
    """Custom-query view over episodic/semantic memories. Mem0's pgvector backend
    creates its own `mem0_memories` table; this one mirrors entries we want for
    future corpus-analysis / maintenance use."""
    __tablename__ = "memory_episodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model = Column(String(100), nullable=False, default=settings.EMBEDDING_MODEL)
    memory_type = Column(String(50), default="episodic", nullable=False)   # "episodic" or "semantic"
    source_thread_id = Column(String(255), nullable=True, index=True)
    meta = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)              # soft-delete marker for dedup


# --------------------------------------------------------------------------- #
# HITL — pending approvals queue                                              #
# --------------------------------------------------------------------------- #
class PendingApproval(Base):
    """Actions paused on a LangGraph interrupt(). Source of truth for the paused
    state is the checkpoint; this row is a queryable index + delivery-state for
    Telegram inline keyboards / web dashboard / expiry sweeper."""
    __tablename__ = "pending_approvals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(String(255), nullable=False, index=True)
    interrupt_id = Column(String(255), nullable=False)         # LangGraph resume token
    action_type = Column(String(100), nullable=False)          # "send_email", "book_flight", ...
    description = Column(Text, nullable=False)                 # human-readable summary
    payload = Column(JSONB, nullable=False)                    # full action data
    status = Column(String(20), default="pending", nullable=False, index=True)  # pending|approved|rejected|discarded|expired
    #   discarded = superseded by an edit/revision; the card stays in history (greyed) so the
    #   record shows what was proposed before the master changed it.
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_via = Column(String(50), nullable=True)           # "telegram", "web", "whatsapp"


# --------------------------------------------------------------------------- #
# Email management (Phase 2)                                                  #
# --------------------------------------------------------------------------- #
class EmailLog(Base):
    """Per-email classification + response audit trail."""
    __tablename__ = "email_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gmail_message_id = Column(String(255), unique=True, nullable=False, index=True)
    subject = Column(String(500), nullable=True)
    sender = Column(String(255), nullable=True, index=True)
    classification = Column(String(20), nullable=True)          # "spam", "fyi", "action_required"
    draft_response = Column(Text, nullable=True)
    response_complexity = Column(String(20), nullable=True)     # "simple", "complex"
    auto_sent = Column(Boolean, default=False, nullable=False)
    approved = Column(Boolean, nullable=True)
    # Multi-dimensional triage (Turn 17.8, migration 003): the full
    # EmailTriageResult — classification (dual-written with the column above so
    # they can't drift), urgency, intent, confidence, suggested_action. Also the
    # natural owner_id home if the inbox goes multi-user (Phase 4).
    meta = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# --------------------------------------------------------------------------- #
# Audit trail — every tool execution                                          #
# --------------------------------------------------------------------------- #
class AuditTrail(Base):
    __tablename__ = "audit_trail"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(String(255), nullable=True, index=True)
    action = Column(String(200), nullable=False)
    tool_name = Column(String(100), nullable=False, index=True)
    safety_level = Column(String(20), nullable=False)           # "safe", "notify", "approve", "blocked"
    input_summary = Column(Text, nullable=True)
    output_summary = Column(Text, nullable=True)
    success = Column(Boolean, default=True, nullable=False)
    error = Column(Text, nullable=True)
    cost_usd = Column(Float, default=0.0, nullable=False)
    latency_ms = Column(Integer, nullable=True)                 # tool execution time (Turn 17.9, migration 004)
    executed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


# --------------------------------------------------------------------------- #
# LLM usage — every call, with langfuse cross-link                            #
# --------------------------------------------------------------------------- #
class LLMUsageLog(Base):
    """Powers the cost dashboard and gives us a join key into Langfuse traces."""
    __tablename__ = "llm_usage_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model = Column(String(100), nullable=False, index=True)
    task_type = Column(String(50), nullable=False)
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    cost_usd = Column(Float, default=0.0, nullable=False)
    tool_name = Column(String(100), nullable=True)
    thread_id = Column(String(255), nullable=True, index=True)
    duration_ms = Column(Integer, nullable=True)
    langfuse_trace_id = Column(String(255), nullable=True)      # cross-link into Langfuse UI
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


# --------------------------------------------------------------------------- #
# Document RAG — chunks with contextual retrieval preface                     #
# --------------------------------------------------------------------------- #
class DocumentChunk(Base):
    """Chunks of an ingested document, embedded for RAG.

    Anthropic Contextual Retrieval: `contextual_summary` is an LLM-generated
    50-100 token preface that situates the chunk inside the document. The
    embedded text is `content_with_context` (preface + chunk), which gives
    a measurable lift on top of plain-chunk embeddings.
    """
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    filename = Column(String(500), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    contextual_summary = Column(Text, nullable=True)
    content_with_context = Column(Text, nullable=True)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model = Column(String(100), nullable=False, default=settings.EMBEDDING_MODEL)
    token_count = Column(Integer, default=0, nullable=False)
    meta = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# --------------------------------------------------------------------------- #
# Tool-result archival — keep agent context small                             #
# --------------------------------------------------------------------------- #
class ToolResult(Base):
    """Oversized tool outputs (>TOOL_RESULT_MAX_CHARS) live here. The agent's
    message history holds a `[tool_result:<id>]` placeholder + a short summary;
    the dashboard fetches the full payload on demand."""
    __tablename__ = "tool_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(String(255), nullable=False, index=True)
    tool_name = Column(String(100), nullable=False)
    tool_call_id = Column(String(255), nullable=False)
    full_result = Column(Text, nullable=False)
    summary = Column(Text, nullable=False)
    char_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


# --------------------------------------------------------------------------- #
# Tool embeddings — dynamic top-k tool selection                              #
# --------------------------------------------------------------------------- #
class ToolEmbedding(Base):
    """One row per registered tool. Populated at agent startup by the registry's
    index_all_tools() call. The agent retrieves top-k by cosine similarity
    against the user's message + recent context, plus any tools flagged
    is_always_loaded=True."""
    __tablename__ = "tool_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    embedding_model = Column(String(100), nullable=False, default=settings.EMBEDDING_MODEL)
    is_always_loaded = Column(Boolean, default=False, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# --------------------------------------------------------------------------- #
# Rate-limit audit (Redis sliding-window is authoritative; this is history)   #
# --------------------------------------------------------------------------- #
class RateLimitEvent(Base):
    __tablename__ = "rate_limit_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(String(255), nullable=False, index=True)
    limit_type = Column(String(50), nullable=False)             # "turns_per_hour", "tools_per_turn", "soft_cap_hit"
    limit_value = Column(Integer, nullable=False)
    actual_value = Column(Integer, nullable=False)
    blocked = Column(Boolean, default=True, nullable=False)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class SystemAlert(Base):
    """A '🚨 SYSTEM' alert — Gmail token expired, a scheduled job failing 3×, etc.
    Persisted ONLY so the HUD Activity feed can surface recent alerts; the
    authoritative delivery is still the best-effort Telegram ping in
    failure_alerter.send_system_alert (the two are written independently). Ages off
    the 24h feed naturally — durable unresolved-issue tracking is a later
    readiness-layer concern, not this row. Deliberately NOT audit_trail (that's
    tool-execution-shaped and would fight the feed's _TOOL_MAP)."""
    __tablename__ = "system_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    text = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


# --- Composite indexes for the hottest read paths ---
Index(
    "ix_memory_episodes_active_created",
    MemoryEpisode.is_active,
    MemoryEpisode.created_at,
)
Index(
    "ix_pending_approvals_status_expires",
    PendingApproval.status,
    PendingApproval.expires_at,
)
Index(
    "ix_document_chunks_doc_chunk",
    DocumentChunk.document_id,
    DocumentChunk.chunk_index,
)
