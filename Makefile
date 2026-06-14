# Jarvis dev targets. The eval + coverage tooling runs INSIDE the backend
# container (it needs the live stack: Postgres + Redis + Ollama + reranker + LLM
# keys). No CI pipeline yet (lands Phase 4) — these are runnable local targets.
#
# The golden-query eval is LLM-driven (costs real $, takes minutes) and is kept
# SEPARATE from the deterministic integration tests on purpose.

.PHONY: evals evals-quick evals-baseline evals-compare evals-break coverage test architecture

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

# Regenerate the auto-generated architecture docs (the mechanical half). The host
# conda env lacks the deps, so the generator runs IN the container; docker-compose.yml
# lives OUTSIDE the /app mount, so it's copied in (--compose-file is required, else the
# external-services doc flips to a degrade-note and the drift-gate would false-fire).
# Output is copied back to docs/architecture/generated/. Review + commit the result.
architecture:
	docker cp docker-compose.yml jarvis-backend:/tmp/dc.yml
	docker compose exec -T backend sh -c 'rm -rf /tmp/arch && python scripts/gen_architecture.py --out /tmp/arch --compose-file /tmp/dc.yml'
	rm -rf docs/architecture/generated && mkdir -p docs/architecture/generated
	docker cp jarvis-backend:/tmp/arch/. docs/architecture/generated/
	@echo "✓ Regenerated docs/architecture/generated/ — review + 'git add docs/architecture/generated'."
