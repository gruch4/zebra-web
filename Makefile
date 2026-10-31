.PHONY: install lint format test test-backend test-frontend dev-backend dev-frontend emulator up up-dev down

# `make up` / `make up-dev` build the image from this checkout; plain `docker compose up -d` pulls
# the published one from ghcr.io.
COMPOSE_BUILD = docker compose -f docker-compose.yml -f docker-compose.build.yml

install:
	cd backend && uv sync
	cd frontend && npm ci

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint && npm run format:check && npm run typecheck

format:
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npm run format

test: test-backend test-frontend

# Needs a Postgres database; set TEST_DATABASE_URL (see README).
test-backend:
	cd backend && uv run pytest -q

test-frontend:
	cd frontend && npm test -- --run

dev-backend:
	cd backend && uv run alembic upgrade head && PRINTER_ALLOW_LOOPBACK=true uv run uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

emulator:
	cd backend && uv run python -m app.printer.emulator --host 127.0.0.1 --port 9100

up:
	$(COMPOSE_BUILD) up -d --build

up-dev:
	$(COMPOSE_BUILD) --profile dev up --build

down:
	$(COMPOSE_BUILD) --profile dev down
