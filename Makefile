SHELL := /bin/bash

CONDA_ENV ?= edu-ai
PY_RUN ?= conda run --name $(CONDA_ENV)

.PHONY: env-init setup setup-backend setup-frontend backend-dev migrate seed-sources \
	acquisition-api acquisition-scheduler acquisition-worker source-smoke \
	governance-scheduler governance-worker governance-fake-check governance-live-smoke \
	content-scheduler content-worker content-stack-up \
	api-generate api-contract-check agent-api-generate agent-api-contract-check \
	agent-workbench-dev agent-workbench-ui agent-workbench-eval agent-portfolio-check \
	infra-up stack-up governance-stack-up infra-down infra-status infra-logs \
	backend-format backend-format-check backend-lint backend-typecheck backend-test \
	backend-integration-test backend-check \
	python-lock python-lock-check release-tool-check release-bundle \
	release-prod \
	frontend-format frontend-format-check frontend-lint frontend-typecheck frontend-test \
	frontend-build frontend-check \
	check doctor

env-init:
	@test -f .env || cp .env.example .env
	@echo "Local configuration is ready at .env"

setup: setup-backend setup-frontend

setup-backend:
	$(PY_RUN) python -m pip install --require-hashes -r backend/requirements/dev.lock
	$(PY_RUN) python -m pip install --no-deps --no-build-isolation -e ./backend

python-lock:
	cd backend && CUSTOM_COMPILE_COMMAND="make python-lock" \
		../scripts/compile-python-locks.sh

python-lock-check:
	bash scripts/check-python-locks.sh

setup-frontend:
	npm ci --prefix frontend

backend-dev:
	$(PY_RUN) python -c 'import uvicorn; from app.core.config import get_settings; settings = get_settings(); uvicorn.run("app.api_main:app", host=settings.app_host, port=settings.app_port, reload=True)'

migrate:
	$(PY_RUN) alembic -c backend/alembic.ini upgrade head

seed-sources:
	$(PY_RUN) python -m app.seed_sources

acquisition-api:
	$(PY_RUN) python -m uvicorn app.api_main:app --host 127.0.0.1 --port 8000

acquisition-scheduler:
	$(PY_RUN) python -m app.scheduler_main

acquisition-worker:
	$(PY_RUN) python -m app.worker_main

source-smoke:
	$(PY_RUN) python -m app.live_smoke

governance-scheduler:
	$(PY_RUN) python -m app.governance_scheduler_main

governance-worker:
	$(PY_RUN) python -m app.governance_worker_main

content-scheduler:
	$(PY_RUN) python -m app.content_scheduler_main

content-worker:
	$(PY_RUN) python -m app.content_worker_main

governance-fake-check:
	$(PY_RUN) pytest backend/tests/unit/test_governance_delivery.py \
		backend/tests/integration/test_governance_api_e2e.py -q

governance-live-smoke:
	@test -n "$(CANDIDATE_ID)" || { echo "CANDIDATE_ID is required" >&2; exit 2; }
	$(PY_RUN) python -m app.governance_live_smoke --candidate-id "$(CANDIDATE_ID)"

api-generate:
	$(PY_RUN) python backend/scripts/export_openapi.py
	npm run generate:api --prefix frontend

api-contract-check:
	$(PY_RUN) python backend/scripts/export_openapi.py --check
	npm run generate:api:check --prefix frontend

agent-api-generate:
	$(PY_RUN) python backend/scripts/export_agent_workbench_openapi.py
	npm run generate:agent-api --prefix frontend

agent-api-contract-check:
	$(PY_RUN) python backend/scripts/export_agent_workbench_openapi.py --check
	npm run generate:agent-api:check --prefix frontend

agent-workbench-dev:
	AGENT_WORKBENCH_ENABLED=true $(PY_RUN) python -m uvicorn \
		app.agent_workbench_api_main:app --host 127.0.0.1 --port 8010

agent-workbench-ui:
	VITE_AGENT_WORKBENCH_ENABLED=true \
	VITE_AGENT_WORKBENCH_API_BASE_URL=http://127.0.0.1:8010 \
		npm run dev --prefix frontend -- --host 127.0.0.1 --port 5173 --strictPort

agent-workbench-eval:
	cd backend && $(PY_RUN) python -m evals.agent_workbench.runner

agent-portfolio-check: agent-api-contract-check
	cd backend && $(PY_RUN) python -m evals.agent_workbench.runner --check
	$(PY_RUN) pytest backend/tests/unit/test_agent_tools.py \
		backend/tests/unit/test_agent_workbench*.py \
		backend/tests/contract/test_agent_mcp.py \
		backend/tests/contract/test_agent_workbench_model.py -q --no-cov
	npm run test --prefix frontend -- --run \
		src/features/agent-workbench src/app/App.test.tsx

infra-up: env-init
	docker compose up -d postgres minio minio-init

stack-up: env-init
	docker compose up -d --build

governance-stack-up: env-init
	docker compose --profile governance up -d --build governance-scheduler governance-worker

content-stack-up: env-init
	docker compose --profile content up -d --build content-scheduler content-worker

infra-down:
	docker compose down

infra-status:
	docker compose ps

infra-logs:
	docker compose logs --tail=100 postgres minio minio-init

backend-format:
	$(PY_RUN) ruff format backend deploy/release \
		scripts/build_brand_asset_manifest.py scripts/annotate_brand_visual_assets.py

backend-format-check:
	$(PY_RUN) ruff format --check backend deploy/release \
		scripts/build_brand_asset_manifest.py scripts/annotate_brand_visual_assets.py

backend-lint:
	$(PY_RUN) ruff check backend deploy/release \
		scripts/build_brand_asset_manifest.py scripts/annotate_brand_visual_assets.py

backend-typecheck:
	$(PY_RUN) mypy backend/app backend/scripts deploy/release/contract.py \
		deploy/release/deploy.py deploy/release/release_tool.py \
		scripts/build_brand_asset_manifest.py scripts/annotate_brand_visual_assets.py

backend-test:
	$(PY_RUN) pytest backend

backend-integration-test:
	$(PY_RUN) pytest backend/tests/integration -q

backend-check: backend-format-check backend-lint backend-typecheck backend-test

frontend-format:
	npm run format --prefix frontend

frontend-format-check:
	npm run format:check --prefix frontend

frontend-lint:
	npm run lint --prefix frontend

frontend-typecheck:
	npm run typecheck --prefix frontend

frontend-test:
	npm run test --prefix frontend -- --run

frontend-build:
	npm run build --prefix frontend

frontend-check: api-contract-check agent-api-contract-check \
	frontend-format-check frontend-lint frontend-typecheck \
	frontend-test frontend-build

check: backend-check frontend-check

release-tool-check:
	$(PY_RUN) pytest deploy/release/tests -q --no-cov

release-bundle:
	@test -n "$(COMMIT)" || { echo "COMMIT is required" >&2; exit 2; }
	$(PY_RUN) python deploy/release/release_tool.py build-bundle \
		--commit "$(COMMIT)" --output-dir "$${OUTPUT_DIR:-dist/release}"

release-prod:
	@bash scripts/release-prod.sh

doctor:
	DOCTOR_PYTHON="$(DOCTOR_PYTHON)" bash scripts/doctor.sh
