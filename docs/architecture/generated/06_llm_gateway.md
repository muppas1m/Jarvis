<!-- AUTO-GENERATED — do not edit by hand.
     Regenerate with `make architecture` (or scripts/gen_architecture.py).
     Source of truth is the code; edit the code, then regenerate. -->

# LLM Gateway Routing

Every chat completion routes through `app/llm/gateway.py:LLMGateway.complete()`. Slots are built in `app/llm/models.py:get_models()`; `task_type` picks a slot via `TASK_ROUTING`; `force_model="<slot>"` overrides routing for one call.

## Model slots (also the valid `force_model` targets)

| Slot | Model ID | Provider |
|---|---|---|
| `primary` | `groq/llama-3.3-70b-versatile` | groq |
| `fast` | `groq/llama-3.1-8b-instant` | groq |
| `fallback` | `openai/gpt-4o-mini` | openai |
| `contextualizer` | `gemini/gemini-2.5-flash-lite` | google |
| `extractor` | `gemini/gemini-2.5-flash-lite` | google |
| `decision` | `openai/gpt-4o-mini` | openai |

## `task_type` → slot (`TASK_ROUTING`)

| task_type | Slot |
|---|---|
| `classification` | `fast` |
| `drafting` | `primary` |
| `reasoning` | `primary` |
| `summarization` | `fast` |

Any unmapped `task_type` falls back to `primary`.

## Routing precedence (in `complete()`)

1. **Hard cap** — if today's LLM spend ≥ `DAILY_LLM_SPEND_CAP_USD` ($5.00), the gateway raises `CostCapExceededError` and the agent halts until UTC midnight.
2. **Soft cap** — at ≥ 80% of the hard cap (`DAILY_LLM_SOFT_CAP_PCT`), every call is degraded to the `fast` slot (unless `force_model` is set).
3. **force_model** — routes to that named slot (e.g. document contextualization uses `force_model="contextualizer"` to stay OFF the agent's Groq).
4. Otherwise **`TASK_ROUTING[task_type]`**, else `primary`.

On a provider failure the gateway falls over to the `fallback` slot once (no recursion past it).
