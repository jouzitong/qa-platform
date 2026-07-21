.PHONY: dev dev-backend dev-frontend test build sync-index

dev-backend:
	./scripts/start-backend.sh

dev-frontend:
	./scripts/start-frontend.sh

dev:
	./scripts/start-dev.sh

test:
	cd backend && .venv/bin/pytest

build:
	cd frontend && npm run build

sync-index:
	codegraph sync
