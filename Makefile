SHELL := /bin/bash

CONDA_ENV ?= edu-ai
PY_RUN := conda run --name $(CONDA_ENV)

.PHONY: env-init setup setup-backend setup-frontend backend-dev api-generate api-contract-check \
	infra-up infra-down infra-status infra-logs \
	backend-format backend-format-check backend-lint backend-typecheck backend-test backend-check \
	frontend-format frontend-format-check frontend-lint frontend-typecheck frontend-test \
	frontend-build frontend-check \
	check doctor

env-init:
	@test -f .env || cp .env.example .env
	@echo "Local configuration is ready at .env"

setup: setup-backend setup-frontend

setup-backend:
	$(PY_RUN) python -m pip install -e "./backend[dev]"

setup-frontend:
	npm ci --prefix frontend

backend-dev:
	$(PY_RUN) python -c 'import uvicorn; from app.core.config import get_settings; settings = get_settings(); uvicorn.run("app.api_main:app", host=settings.app_host, port=settings.app_port, reload=True)'

api-generate:
	$(PY_RUN) python backend/scripts/export_openapi.py
	npm run generate:api --prefix frontend

api-contract-check:
	$(PY_RUN) python backend/scripts/export_openapi.py --check
	npm run generate:api:check --prefix frontend

infra-up: env-init
	docker compose up -d

infra-down:
	docker compose down

infra-status:
	docker compose ps

infra-logs:
	docker compose logs --tail=100 postgres minio minio-init

backend-format:
	$(PY_RUN) ruff format backend

backend-format-check:
	$(PY_RUN) ruff format --check backend

backend-lint:
	$(PY_RUN) ruff check backend

backend-typecheck:
	$(PY_RUN) mypy backend/app backend/scripts

backend-test:
	$(PY_RUN) pytest backend

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

frontend-check: api-contract-check frontend-format-check frontend-lint frontend-typecheck \
	frontend-test frontend-build

check: backend-check frontend-check

doctor:
	bash scripts/doctor.sh
