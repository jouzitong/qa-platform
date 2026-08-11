.PHONY: dev dev-backend dev-frontend test build sync-index test-skill test-skill-contract install-skill

dev-backend:
	./scripts/start-backend.sh

dev-frontend:
	./scripts/start-frontend.sh

dev:
	./scripts/start-dev.sh

test:
	cd backend && .venv/bin/pytest

test-skill:
	python3 -m unittest discover -s integrations/codex/qa-platform-skill/tests -p 'test_*.py'

test-skill-contract:
	cd backend && .venv/bin/pytest tests/test_skill_import_contract.py

install-skill:
	./scripts/install-codex-skill.sh

build:
	cd frontend && npm run build

sync-index:
	codegraph sync
