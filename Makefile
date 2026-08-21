VENV_PYTHON := .venv/bin/python
PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python3)
ISAAC_LAB_ROOT ?= $(HOME)/IsaacLab
ISAAC_LAB_PYTHON ?= $(if $(wildcard $(ISAAC_LAB_ROOT)/isaaclab.sh),$(ISAAC_LAB_ROOT)/isaaclab.sh -p,$(PYTHON))
BUILD_FLAGS ?= --no-isolation
EXPECTED_VERSION ?= 2.0.0
WHEELHOUSE ?=
SCHEMA_OUT ?= build/schemas
CLEAN_PYTHON_ROOTS := src tests tools examples exts

.PHONY: clean test test-isaac test-release test-all lint format build build-kit build-pack audit-dist audit-kit audit-pack check-version check-release-source validate-config validate-fixture export-schema smoke-optional smoke-isaac-sim smoke-isaac-lab smoke-kit diagnose-isaac

clean:
	rm -rf -- build dist .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find $(CLEAN_PYTHON_ROOTS) -type d -name __pycache__ -prune -exec rm -rf -- {} +
	find src -maxdepth 1 -type d -name '*.egg-info' -prune -exec rm -rf -- {} +

test:
	$(PYTHON) -m pytest -q tests/unit tests/contract

test-isaac:
	CUDA_VISIBLE_DEVICES=0 PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_LAB_PYTHON) -m pytest -q tests/isaac

test-release:
	$(PYTHON) -m pytest -q tests/release

test-all:
	$(MAKE) test
	$(PYTHON) -m pytest -q tests/integration
	$(MAKE) test-release
	$(MAKE) test-isaac

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

build: check-version check-release-source
	$(PYTHON) -m build $(BUILD_FLAGS)
	$(MAKE) audit-dist

build-kit: check-version check-release-source
	$(PYTHON) tools/release/build_kit_extension.py
	$(MAKE) audit-kit

build-pack: check-version check-release-source
	@test -n "$(WHEELHOUSE)" || { echo "WHEELHOUSE is required" >&2; exit 2; }
	$(PYTHON) tools/release/build_acoustic_pack.py --wheelhouse "$(WHEELHOUSE)"
	$(MAKE) audit-pack

audit-dist:
	$(PYTHON) tools/release/audit_distribution.py --dist-dir dist

audit-kit:
	$(PYTHON) tools/release/audit_kit_archive.py dist/kit/isaac_audio_sensors.omni-$(EXPECTED_VERSION).zip

audit-pack:
	$(PYTHON) tools/release/audit_acoustic_pack.py dist/packs/isaac_audio_sensors_acoustic_pack-l2l3-$(EXPECTED_VERSION)-linux_x86_64-cp312.tar.gz

check-version:
	$(PYTHON) tools/release/check_version_sync.py

check-release-source:
	$(PYTHON) tools/release/check_release_source.py

validate-config:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors validate-config examples/configs/isaac_audio_sensors_demo.toml

validate-fixture:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors dataset validate tests/fixtures/recording/session

export-schema:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors export-schema --out $(SCHEMA_OUT)/audio_sensor_frame.v1.schema.json
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors export-schema --schema dataset-manifest --out $(SCHEMA_OUT)/audio_dataset_manifest.v1.schema.json
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors export-schema --schema calibration-profile --out $(SCHEMA_OUT)/audio_calibration_profile.v1.schema.json

smoke-optional:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) tools/smoke/optional_audio.py

smoke-isaac-sim:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_LAB_PYTHON) tools/smoke/live_isaac_sim_audio_smoke.py

smoke-isaac-lab:
	CUDA_VISIBLE_DEVICES=0 PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_LAB_PYTHON) tools/smoke/live_isaac_lab_audio_smoke.py

smoke-kit:
	PYTHONPATH=$(CURDIR)/src:$(CURDIR)/exts/isaac_audio_sensors.omni:$(CURDIR)/tools/smoke:$${PYTHONPATH} $(ISAAC_LAB_PYTHON) tools/smoke/live_omniverse_extension_ux.py

diagnose-isaac:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) tools/smoke/diagnose_isaac_gpu_audio.py
