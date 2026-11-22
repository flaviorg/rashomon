PY ?= .venv/bin/python
BIN := $(dir $(PY))

.PHONY: install lint format test cov demo graph svg docs check clean

install:
	$(or $(PYTHON),python3) -m venv .venv
	$(BIN)pip install -e ".[dev]"

lint:
	$(BIN)ruff check .
	$(BIN)ruff format --check .

format:
	$(BIN)ruff format .
	$(BIN)ruff check --fix .

test:
	$(BIN)pytest

cov:
	$(BIN)pytest --cov --cov-report=term-missing

demo:
	$(BIN)rashomon demo

graph:
	$(PY) scripts/gen_graph.py

svg:
	$(PY) scripts/gen_demo_svg.py

docs: graph svg

check: lint test
	$(PY) scripts/gen_graph.py --check

clean:
	rm -rf .rashomon .pytest_cache .ruff_cache .coverage dist build
