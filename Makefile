# qa-agent-evals - every target works without API keys except `run` (real run).
SHELL := /bin/bash
UV ?= uv
PY := $(UV) run python
TASKS ?=
ARGS ?=

.PHONY: help setup history test test-unit test-targets validate run dry-run grade report export estimate docker-image lint clean

help:
	@echo "make setup        install Python (uv) and Node dependencies"
	@echo "make test         unit tests + both target libraries' own suites"
	@echo "make validate     prove every task's graders (reference passes, flawed fail, cheats caught)"
	@echo "make dry-run      run the whole pipeline with scripted fake models (no keys, no cost)"
	@echo "make run          REAL run of every model and harness (needs API keys; asks before spending)"
	@echo "make run DRY_RUN=1  same as make dry-run"
	@echo "make report       regenerate results/results.md, summary.csv and charts from results/runs"
	@echo "make grade TASK=<id> DIFF=<file>  grade a diff against one task"
	@echo "make estimate     estimate the cost of a real run (SMOKE=<jsonl> for a measured estimate)"
	@echo "make export       experimental Archipelago-style verifier export to build/archipelago"
	@echo "make history      rebuild the target libraries' git history into .history/"

setup:
	$(UV) sync
	cd target/ledgerkit && npm ci --no-audit --no-fund

history:
	$(PY) -m tools.rebuild_history

test: test-unit test-targets

test-unit:
	$(UV) run pytest tests

test-targets:
	cd target/shopcore && $(UV) run --project ../.. pytest -q -p no:cacheprovider
	cd target/ledgerkit && npx vitest run && npx tsc --noEmit

validate:
	$(PY) -m tools.rebuild_history
	$(PY) -m validation.validate_tasks $(TASKS) $(ARGS)
	$(PY) -m tools.task_catalog

ifeq ($(DRY_RUN),1)
run: dry-run
else
run:
	$(PY) -m harness.run $(if $(TASKS),--tasks $(TASKS)) $(ARGS)
endif

dry-run:
	$(PY) -m harness.run --dry-run $(if $(TASKS),--tasks $(TASKS)) $(ARGS)

grade:
	@test -n "$(TASK)" -a -n "$(DIFF)" || (echo "usage: make grade TASK=<task_id> DIFF=<patch file>"; exit 2)
	$(PY) -m graders --task $(TASK) --diff $(DIFF) $(ARGS)

report:
	$(PY) -m analysis.report $(ARGS)

export:
	$(PY) -m tools.export_archipelago $(ARGS)

estimate:
	$(PY) -m tools.estimate_cost $(if $(SMOKE),--smoke $(SMOKE)) $(ARGS)

docker-image:
	docker build -t qa-agent-evals-sandbox:1 -f harness/docker/Dockerfile .

lint:
	$(UV) run ruff check harness graders analysis validation tools tests

clean:
	rm -rf .history .scratch build results/.tmp
