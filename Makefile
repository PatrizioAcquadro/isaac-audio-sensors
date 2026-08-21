.DEFAULT_GOAL := _require-target

VENV_PYTHON := .venv/bin/python
PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python3)
ISAAC_LAB_ROOT ?= $(HOME)/IsaacLab
ISAAC_LAB_PYTHON ?= $(if $(wildcard $(ISAAC_LAB_ROOT)/isaaclab.sh),$(ISAAC_LAB_ROOT)/isaaclab.sh -p,$(PYTHON))
BUILD_FLAGS ?= --no-isolation
WHEELHOUSE ?=
SCHEMA_OUT ?= build/schemas
SOURCE_PYTHONPATH := $(CURDIR)/src:$${PYTHONPATH}
KIT_PYTHONPATH := $(CURDIR)/src:$(CURDIR)/exts/isaac_audio_sensors.omni:$(CURDIR)/tools/smoke:$${PYTHONPATH}
CLEAN_PYTHON_ROOTS := src tests tools examples exts

.PHONY: _require-target
_require-target:
	@echo "Specify a target (for example: make check)." >&2
	@exit 2

# Quality gates
.PHONY: check test test-isaac test-release lint format
check:
	$(PYTHON) tools/release/check_version_sync.py
	$(MAKE) lint
	git diff --check
	$(MAKE) test
	$(PYTHON) -m pytest -q tests/integration
	$(MAKE) test-release

test:
	$(PYTHON) -m pytest -q

test-isaac:
	CUDA_VISIBLE_DEVICES=0 PYTHONPATH=$(SOURCE_PYTHONPATH) $(ISAAC_LAB_PYTHON) -m pytest -q tests/isaac

test-release:
	$(PYTHON) -m pytest -q tests/release

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

# Release
.PHONY: release
release:
	@test -n "$(WHEELHOUSE)" || { echo "WHEELHOUSE is required" >&2; exit 2; }
	$(PYTHON) tools/release/check_version_sync.py
	$(PYTHON) tools/release/check_release_source.py
	$(PYTHON) tools/release/build_kit_extension.py --wheelhouse "$(WHEELHOUSE)" --validate-wheelhouse
	rm -rf -- dist build/lib build/bdist.* src/isaac_audio_sensors.egg-info
	$(PYTHON) -m build $(BUILD_FLAGS)
	$(PYTHON) tools/release/build_kit_extension.py --wheelhouse "$(WHEELHOUSE)"
	$(PYTHON) tools/release/audit_release_artifacts.py --dist-dir dist --wheelhouse "$(WHEELHOUSE)"

# Contract utilities
.PHONY: validate-config validate-fixture export-schema
validate-config:
	PYTHONPATH=$(SOURCE_PYTHONPATH) $(PYTHON) -m isaac_audio_sensors validate-config examples/configs/isaac_audio_sensors_demo.toml

validate-fixture:
	PYTHONPATH=$(SOURCE_PYTHONPATH) $(PYTHON) -m isaac_audio_sensors dataset validate tests/fixtures/recording/session

export-schema:
	PYTHONPATH=$(SOURCE_PYTHONPATH) $(PYTHON) -m isaac_audio_sensors export-schema --out $(SCHEMA_OUT)/audio_sensor_frame.v1.schema.json
	PYTHONPATH=$(SOURCE_PYTHONPATH) $(PYTHON) -m isaac_audio_sensors export-schema --schema dataset-manifest --out $(SCHEMA_OUT)/audio_dataset_manifest.v1.schema.json
	PYTHONPATH=$(SOURCE_PYTHONPATH) $(PYTHON) -m isaac_audio_sensors export-schema --schema calibration-profile --out $(SCHEMA_OUT)/audio_calibration_profile.v1.schema.json

# Live runtime gates
.PHONY: smoke-optional smoke-isaac-sim smoke-isaac-lab smoke-kit diagnose-isaac
smoke-optional:
	PYTHONPATH=$(SOURCE_PYTHONPATH) $(PYTHON) tools/smoke/optional_audio.py

smoke-isaac-sim:
	PYTHONPATH=$(SOURCE_PYTHONPATH) $(ISAAC_LAB_PYTHON) tools/smoke/live_isaac_sim_audio_smoke.py

smoke-isaac-lab:
	CUDA_VISIBLE_DEVICES=0 PYTHONPATH=$(SOURCE_PYTHONPATH) $(ISAAC_LAB_PYTHON) tools/smoke/live_isaac_lab_audio_smoke.py

smoke-kit:
	CUDA_VISIBLE_DEVICES=0 PYTHONPATH=$(KIT_PYTHONPATH) $(ISAAC_LAB_PYTHON) tools/smoke/live_omniverse_extension_ux.py

diagnose-isaac:
	PYTHONPATH=$(SOURCE_PYTHONPATH) $(PYTHON) tools/smoke/diagnose_isaac_gpu_audio.py

# Cleanup
.PHONY: clean
clean:
	rm -rf -- build dist .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find $(CLEAN_PYTHON_ROOTS) -type d -name __pycache__ -prune -exec rm -rf -- {} +
	find src -maxdepth 1 -type d -name '*.egg-info' -prune -exec rm -rf -- {} +
