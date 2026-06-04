.PHONY: help install dev-up dev-down migrate seed test lint format build

help:
	@echo "AEAOP — Autonomous Enterprise AI Operations Platform"
	@echo ""
	@echo "Commands:"
	@echo "  make install     Install Python dependencies"
	@echo "  make dev-up      Start all services via Docker Compose"
	@echo "  make dev-down    Stop all services"
	@echo "  make migrate     Run database migrations"
	@echo "  make seed        Seed initial data"
	@echo "  make test        Run test suite"
	@echo "  make lint        Run ruff linter"
	@echo "  make format      Format code with ruff"
	@echo "  make pull-models Pull required AI models (Ollama)"
	@echo "  make setup-all   Full first-time setup"

install:
	pip install -r requirements.txt

dev-up:
	docker compose -f docker-compose.dev.yml up -d
	@echo "Waiting for services to be ready..."
	@sleep 10
	@echo "Services started. Run 'make migrate' to initialize databases."

dev-down:
	docker compose -f docker-compose.dev.yml down

migrate:
	alembic -c backend/alembic.ini upgrade head
	@echo "Migrations complete."

seed:
	python scripts/setup/seed_database.py
	python scripts/setup/create_default_tenant.py
	@echo "Seed data loaded."

pull-models:
	ollama pull qwen3:14b
	ollama pull nomic-embed-text:v2
	@echo "For production, also run:"
	@echo "  ollama pull qwen3:72b"
	@echo "  ollama pull qwen2.5-coder:32b"

setup-all: install dev-up migrate seed pull-models
	@echo ""
	@echo "AEAOP setup complete!"
	@echo "NOC Service:     http://localhost:8001/docs"
	@echo "SOC Service:     http://localhost:8002/docs"
	@echo "AI Service:      http://localhost:8006/docs"
	@echo "Frontend:        http://localhost:3000"
	@echo "Grafana:         http://localhost:3001"
	@echo "Kibana:          http://localhost:5601"

# Run individual services
run-noc:
	uvicorn backend.services.noc_service.main:app --reload --port 8001

run-soc:
	uvicorn backend.services.soc_service.main:app --reload --port 8002

run-ai:
	uvicorn backend.services.ai_service.main:app --reload --port 8006

run-rag:
	uvicorn backend.services.rag_service.main:app --reload --port 8005

run-healing:
	uvicorn backend.services.healing_service.main:app --reload --port 8013

run-auth:
	uvicorn backend.services.auth_service.main:app --reload --port 8009

# Testing
test:
	pytest tests/ -v --asyncio-mode=auto

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

# Code quality
lint:
	ruff check backend/ agents/

format:
	ruff format backend/ agents/

# Database
db-shell:
	docker exec -it aeaop-postgres psql -U aeaop -d aeaop

redis-cli:
	docker exec -it aeaop-redis redis-cli

# Logs
logs-noc:
	docker compose -f docker-compose.dev.yml logs -f noc-service

logs-ai:
	docker compose -f docker-compose.dev.yml logs -f ai-service
