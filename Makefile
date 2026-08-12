.PHONY: install test run live-eval evaluate docker-up

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

install:
	$(PYTHON) -m pip install -e '.[dev]'

test:
	$(PYTHON) -m pytest --cov=app --cov-report=term-missing

run:
	$(PYTHON) -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8080

live-eval:
	$(PYTHON) scripts/run_live_evaluation.py
	$(PYTHON) scripts/evaluate_predictions.py \
		--predictions artifacts/live/predictions.csv \
		--audit artifacts/live/audit.json

evaluate:
	$(PYTHON) scripts/evaluate_predictions.py

docker-up:
	docker compose up --build
