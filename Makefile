# Menged Task Runner (Node.js npm-scripts style)
# Run `make` or `make help` to see all available commands.

VENV ?= .venv/bin
PYTHON = $(shell if [ -d "$(VENV)" ]; then echo "$(VENV)/python"; else echo "python3"; fi)
UVICORN = $(shell if [ -d "$(VENV)" ]; then echo "$(VENV)/uvicorn"; else echo "uvicorn"; fi)
PYTEST = $(shell if [ -d "$(VENV)" ]; then echo "$(VENV)/pytest"; else echo "pytest"; fi)
ALEMBIC = $(shell if [ -d "$(VENV)" ]; then echo "$(VENV)/alembic"; else echo "alembic"; fi)

# Defaults for recording a new simulated route
START ?= Merkato
DEST ?= Bole Medhanialem

.PHONY: help dev start test test-fast test-simulate migrate migrate-new gazetteer record-demo demo-info clean

help:
	@echo "Available Menged commands:"
	@echo "  make dev                 - Run development server with live reload"
	@echo "  make start               - Run server without reload (production mode)"
	@echo "  make test                - Run all 33 automated tests"
	@echo "  make test-simulate       - Run only the simulation verification tests"
	@echo "  make migrate             - Apply database migrations (alembic upgrade head)"
	@echo "  make migrate-new M=\"...\" - Create a new migration revision"
	@echo "  make gazetteer           - Rebuild offline 3,400+ Addis Ababa places list"
	@echo "  make demo-info           - Show current simulated demo route details"
	@echo "  make record-demo         - Change/record a new demo trip for /simulate"
	@echo "                             Usage: make record-demo START=\"Piassa\" DEST=\"Megenagna\""
	@echo "  make clean               - Clean up Python cache and temporary files"

# --- Server -------------------------------------------------------------------
dev:
	$(UVICORN) app.main:app --reload --port 8000

start:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000

# --- Tests --------------------------------------------------------------------
test:
	$(PYTEST) -v

test-fast:
	$(PYTEST) -q

test-simulate:
	$(PYTEST) tests/test_simulate.py -v

# --- Database -----------------------------------------------------------------
migrate:
	$(ALEMBIC) upgrade head

migrate-new:
	@if [ -z "$(M)" ]; then echo "Error: specify a message with M=\"description\""; exit 1; fi
	$(ALEMBIC) revision --autogenerate -m "$(M)"

# --- Data & Simulation --------------------------------------------------------
gazetteer:
	$(PYTHON) -m scripts.build_gazetteer

demo-info:
	@$(PYTHON) -c "import json; d=json.load(open('app/demo/demo_trip.json')); print('\nCurrent /simulate Route:\n  Start:       ' + d['start']['name'] + f' ({d[\"start\"][\"lat\"]}, {d[\"start\"][\"lon\"]})\n  Destination: ' + d['dest']['name'] + f' ({d[\"dest\"][\"lat\"]}, {d[\"dest\"][\"lon\"]})\n  Distance:    ' + f'{d[\"route\"][\"distance_m\"]/1000:.1f} km\n  Duration:    ' + f'{d[\"route\"][\"duration_s\"]/60:.0f} min\n  Places:      ' + f'{len(d.get(\"places\", []))} places\n  Streets:     ' + f'{len(d.get(\"streets\", []))} sampled streets\n')"

record-demo:
	@echo "Recording new /simulate route from '$(START)' to '$(DEST)'..."
	$(PYTHON) -m scripts.record_demo "$(START)" "$(DEST)"
	@$(MAKE) demo-info

# --- Housekeeping -------------------------------------------------------------
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
