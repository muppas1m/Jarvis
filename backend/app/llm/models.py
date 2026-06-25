"""
Model registry — single source of truth for which LLMs we route to.

Three slots: `primary`, `fast`, `fallback`. Their concrete model IDs come
from settings (PRIMARY_MODEL, FAST_MODEL, FALLBACK_MODEL). Swap any of those
in `.env` and restart — no code change needed across the codebase.

`TASK_ROUTING` maps logical task types ("classification", "reasoning",
"drafting", "summarization") to slot names so callers stay decoupled from
specific models.
"""
from dataclasses import dataclass
from functools import cache

from app.config import settings


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    provider: str
    max_tokens: int
    cost_per_1k_input: float
    cost_per_1k_output: float


# Cost registry. Models not listed default to $0 (free / local / unknown).
# Costs are USD per 1k tokens, in the order (input, output).
# Update this map when a new paid provider gets plugged into PRIMARY/FAST/FALLBACK.
KNOWN_COSTS: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-sonnet-4-20250514": (0.003, 0.015),
    "claude-haiku-4-5-20251001": (0.0008, 0.004),
    "claude-opus-4-7": (0.015, 0.075),
    # OpenAI
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-5": (0.005, 0.015),
    # Gemini (paid tier — see project_mem0_extraction_gemini_swap). Listed so the
    # memory-extraction + contextualizer slots attribute real $ instead of $0.
    "gemini-2.5-flash-lite": (0.0001, 0.0004),
    # Groq + Ollama → free/local → not listed → $0
}


def _infer_provider(model_id: str) -> str:
    """LiteLLM model-id convention: `<provider>/<model>` for non-OpenAI providers."""
    if model_id.startswith("ollama/"):
        return "ollama"
    if model_id.startswith("groq/"):
        return "groq"
    if model_id.startswith("gemini/"):
        return "google"
    if "claude" in model_id:
        return "anthropic"
    if "gpt" in model_id:
        return "openai"
    return "unknown"


def _build_model(model_id: str) -> ModelConfig:
    """Build a ModelConfig from a model ID string. Costs default to $0 if unknown."""
    short_id = model_id.split("/")[-1]
    costs = KNOWN_COSTS.get(short_id, (0.0, 0.0))
    return ModelConfig(
        model_id=model_id,
        provider=_infer_provider(model_id),
        max_tokens=8192,
        cost_per_1k_input=costs[0],
        cost_per_1k_output=costs[1],
    )


@cache
def get_models() -> dict[str, ModelConfig]:
    """Build the model registry from env vars. Cached — settings don't change at
    runtime, so building this dict once and reusing it saves work in the cost
    tracker (called on every LLM completion)."""
    return {
        "primary": _build_model(settings.PRIMARY_MODEL),
        "fast": _build_model(settings.FAST_MODEL),
        "fallback": _build_model(settings.FALLBACK_MODEL),
        # Dedicated slot for document contextualization — the paid Gemini, OFF
        # the agent's saturating Groq. Routed via force_model="contextualizer".
        "contextualizer": _build_model(settings.CONTEXTUALIZER_MODEL),
        # Dedicated slot for owned memory fact-extraction — same paid Gemini, off
        # the agent's Groq. Routed via force_model="extractor" (app.memory.extraction).
        "extractor": _build_model(settings.MEMORY_EXTRACTION_MODEL),
    }


# Logical-task → slot-name routing. Any other call site that doesn't supply a
# task_type falls back to "primary".
TASK_ROUTING: dict[str, str] = {
    "classification": "fast",     # email classification, intent detection, safety triage
    "reasoning": "primary",       # complex tasks, planning, full agent responses
    "drafting": "primary",        # email drafts, long-form responses
    "summarization": "fast",      # digests, news briefs
}
