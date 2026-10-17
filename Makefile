# RSSI Simulator — tâches courantes
# Linux : make <cible>   ·   Windows : make <cible> PY=python (Git Bash / MSYS2) ou commandes équivalentes

PY ?= python3
VENV ?= .venv
ifeq ($(OS),Windows_NT)
  BIN := $(VENV)/Scripts
else
  BIN := $(VENV)/bin
endif
PYTHON := $(BIN)/python

.PHONY: help venv install install-ai run run-headless test coverage package-win package-linux clean

help:
	@echo "Cibles : install, install-ai, run, run-headless, test, coverage, package-linux, package-win, clean"

$(PYTHON):
	$(PY) -m venv $(VENV)

venv: $(PYTHON)

install: venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

install-ai: venv
	$(PYTHON) -m pip install -r requirements-ai.txt

run:
	$(PYTHON) main.py

run-headless:
	$(PYTHON) main.py --headless --scenario hopital --seed 42

test:
	SDL_VIDEODRIVER=offscreen SDL_AUDIODRIVER=dummy $(PYTHON) -m pytest

coverage:
	SDL_VIDEODRIVER=offscreen SDL_AUDIODRIVER=dummy $(PYTHON) -m pytest --cov=game --cov-report=term-missing --cov-report=html --cov-fail-under=80

package-linux:
	$(PYTHON) build.py --sep ":"

package-win:
	$(PYTHON) build.py --sep ";"

clean:
	rm -rf build dist htmlcov .pytest_cache .coverage
	find . -name "__pycache__" -type d -prune -not -path "./$(VENV)/*" -exec rm -rf {} +
