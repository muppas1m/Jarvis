# Jarvis dev targets. The eval + coverage tooling runs INSIDE the backend
# container (it needs the live stack: Postgres + Redis + Ollama + reranker + LLM
# keys). No CI pipeline yet (lands Phase 4) — these are runnable local targets.
#
# The golden-query eval is LLM-driven (costs real $, takes minutes) and is kept
# SEPARATE from the deterministic integration tests on purpose.

.PHONY: evals evals-quick evals-baseline evals-compare evals-break coverage test

# Full golden-query eval (real LLM turns + judge). Cost-isolated from the
# production cap via eval_mode. Writes a timestamped report under evals/results/.
evals:
	docker compose exec -T backend python evals/runner.py

# Fast subset for iteration — first 3 general queries, no RAG seeding.
evals-quick:
	docker compose exec -T backend python evals/runner.py --limit 3 --no-rag

# Establish / refresh the committed baseline.
evals-baseline:
	docker compose exec -T backend python evals/runner.py --baseline

# Compare the newest result against baseline.json (hard-rule = gate).
evals-compare:
	docker compose exec -T backend python evals/compare.py

# Regression demo: remove a tool and prove the hard rule catches it (exit 1).
evals-break:
	docker compose exec -T backend python evals/runner.py --limit 4 --no-rag --break-tool memory_search

# Line coverage of application code (Turn 20.5 task y — config only, no gate yet).
coverage:
	docker compose exec -T backend python -m pytest --cov=app --cov-report=term-missing tests/

# Deterministic test suite (no LLM eval).
test:
	docker compose exec -T backend python -m pytest tests/ -q
