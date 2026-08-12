.PHONY: install test run live-eval evaluate docker-up

install:
	python -m pip install -e '.[dev]'

test:
	python -m pytest --cov=app --cov-report=term-missing

run:
	uvicorn app.main:app --reload --host 127.0.0.1 --port 8080

live-eval:
	python scripts/run_live_evaluation.py
	python scripts/evaluate_predictions.py

evaluate:
	python scripts/evaluate_predictions.py

docker-up:
	docker compose up --build
