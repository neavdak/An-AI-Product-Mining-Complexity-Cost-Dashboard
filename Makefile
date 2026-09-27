.PHONY: install install-ml dev test data analyze docker docker-llm

install:
	python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt

install-ml:
	. .venv/bin/activate && pip install -r requirements-ml.txt

dev:
	. .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	. .venv/bin/activate && pytest -q

data:
	. .venv/bin/activate && python -m app.cli generate --out data/sample

analyze:
	. .venv/bin/activate && python -m app.cli analyze --data data/sample --out reports

docker:
	docker compose up --build

docker-llm:
	docker compose --profile llm up --build
