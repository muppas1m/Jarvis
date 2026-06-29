<!-- AUTO-GENERATED — do not edit by hand.
     Regenerate with `make architecture` (or scripts/gen_architecture.py).
     Source of truth is the code; edit the code, then regenerate. -->

# Agent Graph (LangGraph)

Rendered from the compiled `StateGraph` (`app/agent/graph.py:build_graph`) via `get_graph().draw_mermaid()`. The APPROVE-tier interrupt lives inside `tool_executor` (it pauses the graph; resume re-enters the same node).

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	memory_load(memory_load)
	card_resolution(card_resolution)
	agent(agent)
	tool_executor(tool_executor)
	queued_finish(queued_finish)
	persist(persist)
	compact(compact)
	__end__([<p>__end__</p>]):::last
	__start__ --> memory_load;
	agent -.-> persist;
	agent -.-> tool_executor;
	card_resolution -.-> agent;
	card_resolution -.-> persist;
	memory_load --> card_resolution;
	persist --> compact;
	queued_finish --> persist;
	tool_executor -.-> agent;
	tool_executor -.-> queued_finish;
	compact --> __end__;
	tool_executor -.-> tool_executor;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
