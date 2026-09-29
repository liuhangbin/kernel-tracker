.PHONY: help test integration-test lint format debug stop attach log start

help:
	@echo "make test              Run the test suite."
	@echo "make integration-test  Run integration tests in containers."
	@echo "make lint              Check code style (ruff check and black --check)."
	@echo "make format            Fix lint issues and reformat code (ruff and black)."
	@echo "make start             Start uninitialized server environment."
	@echo "make debug             Start an initialized debug environment."
	@echo "make stop              Stop the running containers."
	@echo "make attach            Attach to the running kernel-tracker container."
	@echo "make log               Show the error log from the running container."

test:
	uv run pytest tests/

integration-test: start
	@podman-compose exec kernel-tracker bash tests/run || \
		{ echo "*** Testing failed. Container is left running (use make stop)"; exit 1; }
	podman-compose down

lint:
	uv run ruff check src/ tests/
	uv run black --check src/ tests/

format:
	uv run ruff check --fix src/ tests/
	uv run black src/ tests/

start:
	podman-compose up -d --build
	@echo "Waiting for services..."
	@until curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/health; do \
		sleep 2; \
	done
	@echo "Services are up at http://localhost:8080/"

debug: start
	podman-compose exec kernel-tracker bash tests/run

stop:
	podman-compose down

attach:
	podman-compose exec kernel-tracker /bin/bash

log:
	podman-compose exec kernel-tracker cat /data/log/error.log
