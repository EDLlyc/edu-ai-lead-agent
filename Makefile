SHELL := /bin/bash

CONDA_ENV ?= edu-ai
PY_RUN ?= conda run --name $(CONDA_ENV)

.PHONY: env-init setup setup-backend setup-frontend backend-dev migrate seed-sources \
	acquisition-api acquisition-scheduler acquisition-worker source-smoke \
	governance-scheduler governance-worker governance-fake-check governance-live-smoke \
	content-scheduler content-worker content-stack-up \
	official-account-local-worker official-account-local-demo \
	official-account-local-live-smoke official-account-local-export \
	wechat-official-account-draft-config-check \
	ip-asset-worker ip-asset-import-dry-run ip-asset-stack-up ip-asset-ui \
	ip-asset-demo-preflight \
	api-generate api-contract-check agent-api-generate agent-api-contract-check \
	topic-rerank-eval \
	brand-retrieval-eval \
	visual-retrieval-eval \
	ip-asset-grounded-eval-check ip-asset-grounded-eval-preflight \
	ip-asset-grounded-eval-live ip-asset-grounded-eval-report \
	ip-asset-grounded-eval-compare \
	image-quality-eval \
	eval-check \
	agent-workbench-dev agent-workbench-ui agent-workbench-eval agent-portfolio-check \
	agent-portfolio-capture agent-portfolio-capture-check \
	agent-portfolio-live-zhipu-preflight agent-portfolio-live-zhipu-capture \
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

official-account-local-worker:
	OFFICIAL_ACCOUNT_LOCAL_ENABLED=true \
	OFFICIAL_ACCOUNT_LOCAL_WORKER_ENABLED=true \
		$(PY_RUN) python -m app.official_account_worker_main

official-account-local-demo:
	OFFICIAL_ACCOUNT_LOCAL_ENABLED=true \
	OFFICIAL_ACCOUNT_EDITOR_HANDOFF_ENABLED=true \
	OFFICIAL_ACCOUNT_LOCAL_VISUAL_SEMANTIC_ENABLED=false \
	VISUAL_EMBEDDING_PROVIDER_MODE=disabled \
	AI_PROVIDER_MODE=disabled \
	CONTENT_LLM_RERANK_ENABLED=false \
		docker compose --profile official-account-local up --build \
		official-account-local-frontend

official-account-local-live-smoke:
	@test -n "$(MATERIAL_PACKAGE_ID)" || { echo "MATERIAL_PACKAGE_ID is required" >&2; exit 2; }
	OFFICIAL_ACCOUNT_LOCAL_ENABLED=true \
		docker compose --profile official-account-local up -d --build \
		acquisition-api official-account-local-worker
	OFFICIAL_ACCOUNT_LOCAL_ENABLED=true \
		$(PY_RUN) python -m app.official_account_local_cli live \
		--material-package-id "$(MATERIAL_PACKAGE_ID)"

official-account-local-export:
	@test -n "$(RUN_ID)" || { echo "RUN_ID is required" >&2; exit 2; }
	OFFICIAL_ACCOUNT_LOCAL_ENABLED=true \
		$(PY_RUN) python -m app.official_account_local_cli export \
		--run-id "$(RUN_ID)" \
		--mode "$(if $(MODE),$(MODE),review)" \
		--output-dir "$(if $(OUTPUT_DIR),$(OUTPUT_DIR),output/official-account-local)"

wechat-official-account-draft-config-check:
	docker compose --profile wechat-official-account-draft config --quiet

ip-asset-worker:
	IP_ASSET_HUB_ENABLED=true \
	IP_ASSET_WORKER_ENABLED=true \
		$(PY_RUN) python -m app.ip_asset_worker_main

ip-asset-import-dry-run:
	$(PY_RUN) python -m app.ip_asset_import_main --dry-run \
		--max-assets "$(if $(MAX_ASSETS),$(MAX_ASSETS),500)"

ip-asset-stack-up:
	IP_ASSET_HUB_ENABLED=true \
	IP_ASSET_WORKER_ENABLED=true \
		docker compose --profile ip-assets up -d --build \
		acquisition-api ip-asset-worker

ip-asset-ui:
	VITE_IP_ASSET_HUB_ENABLED=true npm run dev --prefix frontend -- \
		--host 127.0.0.1 --port 5173 --strictPort

ip-asset-demo-preflight:
	$(PY_RUN) python scripts/ip_asset_demo_preflight.py

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

topic-rerank-eval:
	cd backend && $(PY_RUN) python -m evals.topic_rerank.runner --check

brand-retrieval-eval:
	cd backend && $(PY_RUN) python -m evals.brand_retrieval.runner --check

ip-asset-retrieval-eval:
	cd backend && $(PY_RUN) python -m evals.ip_asset_retrieval.runner --check

ip-asset-grounded-eval-check:
	cd backend && $(PY_RUN) python -m evals.ip_asset_retrieval_grounded.authoring --check
	cd backend && $(PY_RUN) python -m evals.ip_asset_retrieval_grounded.runner validate-seed
	cd backend && $(PY_RUN) python -m evals.ip_asset_retrieval_grounded.runner check-canonical

ip-asset-grounded-eval-preflight:
	cd backend && $(PY_RUN) python -m evals.ip_asset_retrieval_grounded.runner preflight-live

ip-asset-grounded-eval-live:
	@test -n "$(OUTPUT)" || (echo "OUTPUT is required" >&2; exit 2)
	cd backend && $(PY_RUN) python -m evals.ip_asset_retrieval_grounded.runner run-live \
		--search-version "$(or $(SEARCH_VERSION),ip-asset-hybrid-v3-rrf)" \
		--output "$(abspath $(OUTPUT))"

ip-asset-grounded-eval-report:
	@test -n "$(RUN)" || (echo "RUN is required" >&2; exit 2)
	@test -n "$(OUTPUT_JSON)" || (echo "OUTPUT_JSON is required" >&2; exit 2)
	@test -n "$(OUTPUT_MARKDOWN)" || (echo "OUTPUT_MARKDOWN is required" >&2; exit 2)
	cd backend && $(PY_RUN) python -m evals.ip_asset_retrieval_grounded.runner report-run \
		--run "$(abspath $(RUN))" --output-json "$(abspath $(OUTPUT_JSON))" \
		--output-markdown "$(abspath $(OUTPUT_MARKDOWN))"

ip-asset-grounded-eval-compare:
	@test -n "$(BASELINE)" || (echo "BASELINE is required" >&2; exit 2)
	@test -n "$(CANDIDATE)" || (echo "CANDIDATE is required" >&2; exit 2)
	@test -n "$(OUTPUT_JSON)" || (echo "OUTPUT_JSON is required" >&2; exit 2)
	@test -n "$(OUTPUT_MARKDOWN)" || (echo "OUTPUT_MARKDOWN is required" >&2; exit 2)
	cd backend && $(PY_RUN) python -m evals.ip_asset_retrieval_grounded.runner compare-runs \
		--baseline "$(abspath $(BASELINE))" --candidate "$(abspath $(CANDIDATE))" \
		--output-json "$(abspath $(OUTPUT_JSON))" \
		--output-markdown "$(abspath $(OUTPUT_MARKDOWN))"

visual-retrieval-eval:
	cd backend && $(PY_RUN) python -m evals.visual_retrieval.runner --check

image-quality-eval:
	cd backend && $(PY_RUN) python -m evals.image_quality.runner --check

eval-check: brand-retrieval-eval image-quality-eval ip-asset-grounded-eval-check \
	ip-asset-retrieval-eval topic-rerank-eval visual-retrieval-eval

agent-portfolio-check: agent-api-contract-check
	cd backend && $(PY_RUN) python -m evals.agent_workbench.runner --check
	$(PY_RUN) pytest backend/tests/unit/test_agent_tools.py \
		backend/tests/unit/test_agent_workbench*.py \
		backend/tests/contract/test_agent_mcp.py \
		backend/tests/contract/test_agent_workbench_model.py -q --no-cov
	npm run test --prefix frontend -- --run \
		src/features/agent-workbench src/app/App.test.tsx

agent-portfolio-capture:
	$(PY_RUN) python scripts/capture_agent_workbench.py deterministic

agent-portfolio-capture-check:
	@test -n "$(CAPTURE_DIR)" || { echo "CAPTURE_DIR is required" >&2; exit 2; }
	$(PY_RUN) python scripts/capture_agent_workbench.py verify "$(CAPTURE_DIR)"

agent-portfolio-live-zhipu-preflight:
	$(PY_RUN) python scripts/capture_agent_workbench.py preflight-live

agent-portfolio-live-zhipu-capture:
	$(PY_RUN) python scripts/capture_agent_workbench.py live-zhipu --execute-authorized-once

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
		scripts/build_brand_asset_manifest.py scripts/annotate_brand_visual_assets.py \
		scripts/capture_agent_workbench.py

backend-format-check:
	$(PY_RUN) ruff format --check backend deploy/release \
		scripts/build_brand_asset_manifest.py scripts/annotate_brand_visual_assets.py \
		scripts/capture_agent_workbench.py

backend-lint:
	$(PY_RUN) ruff check backend deploy/release \
		scripts/build_brand_asset_manifest.py scripts/annotate_brand_visual_assets.py \
		scripts/capture_agent_workbench.py scripts/ip_asset_demo_preflight.py

backend-typecheck:
	$(PY_RUN) mypy backend/app backend/scripts deploy/release/contract.py \
		deploy/release/deploy.py deploy/release/release_tool.py \
		scripts/build_brand_asset_manifest.py scripts/annotate_brand_visual_assets.py \
		scripts/capture_agent_workbench.py scripts/ip_asset_demo_preflight.py

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
