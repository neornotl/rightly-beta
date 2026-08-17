# Tieng Lang - Makefile (Unix/macOS; Windows users: see README python equivalents)

PYTHON ?= python
PIP ?= $(PYTHON) -m pip

.PHONY: setup test lint format mock-demo eval-demo preflight ui offline-setup clean

setup:
	$(PYTHON) -m venv .venv
	$(PIP) install -r requirements.txt -r requirements-dev.txt

offline-setup:
	$(PYTHON) scripts/bootstrap_offline.py --all

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format .

mock-demo:
	$(PYTHON) scripts/ingest_documents.py
	$(PYTHON) scripts/run_mock_demo.py

eval-demo:
	$(PYTHON) -m eval.run_all

preflight:
	$(PYTHON) scripts/preflight.py

ui:
	$(PYTHON) -m streamlit run app/ui.py

clean:
	-rm -rf .pytest_cache .ruff_cache __pycache__ .venv
