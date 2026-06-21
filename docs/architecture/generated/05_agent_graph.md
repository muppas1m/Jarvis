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
	agent(agent)
	tool_executor(tool_executor)
	persist(persist)
	compact(compact)
	__end__([<p>__end__</p>]):::last
	__start__ --> memory_load;
	agent -.-> persist;
	agent -.-> tool_executor;
	memory_load --> agent;
	persist --> compact;
	tool_executor -.-> agent;
	compact --> __end__;
	tool_executor -.-> tool_executor;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
