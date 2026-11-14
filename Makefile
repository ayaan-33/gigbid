.PHONY: install dev up down test test-unit test-contract test-e2e eval eval-smoke seed data demo demo-single lint fmt client graphs checks

PY := uv run python
COMPOSE := docker compose -f infra/docker-compose.yml

install:            ## install python + web deps
	uv sync --extra dev
	cd apps/web && npm ci

dev:                ## full stack in docker (web, api, worker, mcp x3, gigsim, postgres, redis, ollama)
	$(COMPOSE) --profile local up --build

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

lint:
	uv run ruff check .
	uv run ruff format --check .
	cd apps/web && npm run lint && npm run typecheck

fmt:
	uv run ruff check --fix .
	uv run ruff format .

test: test-unit test-contract

test-unit:
	uv run pytest -q tests/unit mcp_servers

test-contract:
	uv run pytest -q tests/contract

test-integration:
	uv run pytest -q -m integration tests/integration

test-e2e:
	cd apps/web && npx playwright test

checks:             ## repo policy checks enforced in CI
	$(PY) scripts/checks/check_prompts_location.py
	$(PY) scripts/checks/check_gigsim_frozen.py
	$(PY) scripts/checks/check_numbers_traced.py

data:               ## preprocess Kaggle downloads into data/processed
	$(PY) -m scripts.data.preprocess_kaggle

seed:               ## generate synthetic personas/clients/jobs + dev set, seed GigSim and portfolio index
	$(PY) -m scripts.data.build_all
	$(PY) -m rag.ingest.run --all

eval:               ## full evaluation suite -> evals/results/*.json
	LLM_CACHE=1 $(PY) -m evals.runners.run_all

eval-smoke:         ## 30-job smoke eval used in CI with failure thresholds
	LLM_CACHE=1 $(PY) -m evals.runners.smoke --jobs 30

demo-single:        ## Part A deliverable: single agent drafts one grounded proposal
	$(PY) -m evals.runners.single_agent_demo

demo:               ## run one job end to end against GigSim and print the approval payload
	$(PY) -m scripts.demo_job

client:             ## regenerate the TypeScript API client from FastAPI's OpenAPI schema
	$(PY) -m scripts.export_openapi > apps/web/openapi.json
	cd apps/web && npm run gen:api

graphs:             ## render both graphs from code into docs/images
	$(PY) -m scripts.render_graphs
