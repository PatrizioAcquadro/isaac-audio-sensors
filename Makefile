VENV_PYTHON := .venv/bin/python
PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python3)
ISAAC_SIM_ROOT ?= $(HOME)/isaacsim
ISAAC_LAB_ROOT ?= $(HOME)/IsaacLab
ISAAC_SIM_COMMAND ?= $(if $(wildcard $(ISAAC_SIM_ROOT)/python.sh),$(ISAAC_SIM_ROOT)/python.sh,$(PYTHON))
ISAAC_LAB_PYTHON ?= $(if $(wildcard $(ISAAC_LAB_ROOT)/isaaclab.sh),$(ISAAC_LAB_ROOT)/isaaclab.sh -p,$(PYTHON))
ISAAC_LAB_PERF_BUDGET_MS ?= 20
ISAAC_DIAGNOSTICS_OUT_DIR ?= outputs/isaac_audio_sensors/diagnostics
BUILD_FLAGS ?= --no-isolation
EXPECTED_VERSION ?= 1.10.0
WHEELHOUSE ?=
CONSUMER_USER ?= pacquadr
CONSUMER_REPO ?= /home/$(CONSUMER_USER)/Desktop/squadbot-av-phase1

.PHONY: test test-full test-fast test-current lint format build build-kit audit-kit build-pack audit-pack artifacts checksums check-version check-release-source audit-dist import-smoke validate-config dataset-validate-fixture export-schema regenerate-traces regenerate-manifests regenerate-reference-dataset measure-writer-memory live-evidence-report live-clean-install consumer-gate live-clean-install-gui live-isaac-sim-audio live-s3-1-pose-velocity live-s3-2-time-gaps live-s3-stress live-isaac-occlusion live-omniverse-extension-ux live-omniverse-extension-ux-screenshots live-guided-workflow live-headless-parity live-reliability live-endurance-capture live-isaac-lab-audio live-isaac-lab-audio-gpu diagnose-isaac alex-audio-showcase

CURRENT_TESTS := \
	tests/test_s4_8_engineering_acquisition_v2.py \
	tests/test_s4_8_engineering_campaign.py \
	tests/test_s4_8_engineering_rehearsal.py \
	tests/test_s4_8_physical_backend.py \
	tests/test_s4_8_preliminary.py

# Keep the established closeout contract: `make test` always runs everything.
test: test-full

test-full:
	$(PYTHON) -m pytest

test-fast:
	$(PYTHON) -m pytest -m "not phase_gate and not hardware"

test-current:
	$(PYTHON) -m pytest $(CURRENT_TESTS)

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

build: check-version
	$(PYTHON) -c "import shutil; from pathlib import Path; shutil.rmtree('dist', ignore_errors=True); Path('dist').mkdir()"
	$(PYTHON) -m build $(BUILD_FLAGS)
	$(PYTHON) scripts/audit_distribution.py --dist-dir dist

build-kit: check-release-source check-version
	$(PYTHON) scripts/build_kit_extension.py
	$(PYTHON) scripts/audit_kit_archive.py dist/kit/isaac_audio_sensors.omni-$(EXPECTED_VERSION).zip

audit-kit:
	$(PYTHON) scripts/audit_kit_archive.py dist/kit/isaac_audio_sensors.omni-$(EXPECTED_VERSION).zip

build-pack: check-release-source check-version
	@test -n "$(WHEELHOUSE)" || { echo "WHEELHOUSE is required: make build-pack WHEELHOUSE=/path/to/wheels" >&2; exit 2; }
	$(PYTHON) scripts/build_acoustic_pack.py --wheelhouse "$(WHEELHOUSE)"

audit-pack:
	$(PYTHON) scripts/audit_acoustic_pack.py dist/packs/isaac_audio_sensors_acoustic_pack-l2l3-$(EXPECTED_VERSION)-linux_x86_64-cp312.tar.gz

checksums:
	$(PYTHON) -c "from pathlib import Path; import hashlib; root=Path('dist'); paths=sorted([*root.glob('*.whl'), *root.glob('*.tar.gz'), *root.glob('kit/*.zip'), *root.glob('packs/*.tar.gz')]); (root/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}\n' for path in paths), encoding='utf-8')"

artifacts: check-release-source check-version
	@test -n "$(WHEELHOUSE)" || { echo "WHEELHOUSE is required: make artifacts WHEELHOUSE=/path/to/wheels" >&2; exit 2; }
	$(MAKE) build
	$(MAKE) build-kit
	$(MAKE) audit-kit
	$(MAKE) build-pack WHEELHOUSE="$(WHEELHOUSE)"
	$(MAKE) audit-pack
	$(MAKE) checksums

check-version:
	$(PYTHON) scripts/check_version_sync.py

check-release-source:
	$(PYTHON) scripts/check_release_source.py

audit-dist:
	$(PYTHON) scripts/audit_distribution.py --dist-dir dist

import-smoke:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -c "import isaac_audio_sensors, sys; print(isaac_audio_sensors.__version__); sys.exit(0 if isaac_audio_sensors.__version__ == '$(EXPECTED_VERSION)' else 1)"

validate-config:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors.cli validate-config configs/isaac_audio_sensors_demo.toml

dataset-validate-fixture:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors dataset validate examples/datasets/reference_session_v1

export-schema:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors.cli export-schema --out docs/schemas/audio_sensor_frame.v1.schema.json
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors.cli export-schema --schema dataset-manifest --out docs/schemas/audio_dataset_manifest.v1.schema.json
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors.cli export-schema --schema calibration-profile --out docs/schemas/audio_calibration_profile.v1.schema.json

regenerate-traces:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) scripts/regenerate_example_traces.py

regenerate-manifests:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) scripts/regenerate_example_manifests.py

regenerate-reference-dataset:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) scripts/regenerate_reference_dataset.py

measure-writer-memory:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) scripts/measure_writer_memory.py --workload all --scale 1.0 --output-json outputs/isaac_audio_sensors/S2/S2.2/memory_telemetry.json

live-evidence-report:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) scripts/generate_live_evidence_report.py

live-clean-install:
	$(PYTHON) scripts/live_clean_install_gate.py --isaac-root "$(ISAAC_SIM_ROOT)"
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/S1/S1.6/clean_install_gate.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

# A "blocked" consumer-gate status is a blocker record, not a passing gate.
consumer-gate:
	$(PYTHON) scripts/run_installed_consumer_gate.py --consumer-repo "$(CONSUMER_REPO)"
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/S1/S1.8/consumer_gate.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-clean-install-gui:
	$(PYTHON) scripts/live_clean_install_gate.py --isaac-root "$(ISAAC_SIM_ROOT)"
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/S1/S1.6/clean_install_gate.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-isaac-sim-audio:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_isaac_sim_audio_smoke.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/isaac_sim_live_smoke.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-s3-1-pose-velocity:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/run_s3_1_live_pose_velocity.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/S3/S3.1/live_isaac_teleport_summary.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-s3-2-time-gaps:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/run_s3_2_live_time_gaps.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/S3/S3.2/live_throttled_capture_summary.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-s3-stress:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_s3_stress_gate.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/S3/S3.8/live_stress_summary.json').read_text()); td=data.get('teardown', {}); sys.exit(0 if data.get('status') == 'passed' and td.get('simulation_app_close_error') is None and td.get('status') in ('passed', 'provisional') else 1)"

live-isaac-occlusion:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_isaac_occlusion_gate.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/isaac_occlusion_live_gate.json').read_text()); ok=data.get('status') == 'passed' and data.get('screenshot', {}).get('status') == 'captured' and pathlib.Path(data['screenshot']['path']).is_file(); sys.exit(0 if ok else 1)"

live-omniverse-extension-ux:
	PYTHONPATH=$(CURDIR)/src:$(CURDIR)/exts/isaac_audio_sensors.omni:$(CURDIR)/scripts:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_omniverse_extension_ux.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/omniverse_extension_live_ux.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-omniverse-extension-ux-screenshots:
	PYTHONPATH=$(CURDIR)/src:$(CURDIR)/exts/isaac_audio_sensors.omni:$(CURDIR)/scripts:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_omniverse_extension_ux.py --require-screenshot
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/omniverse_extension_live_ux.json').read_text()); scenarios=data.get('object_attach_live_qa', {}); required=('generic_scene','molmo_floorplan1'); instruments=data.get('instruments', {}); ok=data.get('status') == 'passed' and instruments.get('status') == 'passed' and instruments.get('compass', {}).get('needle_count', 0) > 0 and instruments.get('meters') and instruments.get('panel', {}).get('status') == 'captured' and pathlib.Path(instruments.get('panel', {}).get('path', '')).is_file() and all(scenarios.get(name, {}).get('screenshot', {}).get('status') == 'captured' and pathlib.Path(scenarios[name]['screenshot']['path']).is_file() for name in required); sys.exit(0 if ok else 1)"

live-guided-workflow:
	PYTHONPATH=$(CURDIR)/src:$(CURDIR)/exts/isaac_audio_sensors.omni:$(CURDIR)/scripts:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_guided_workflow_gate.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/S2/S2.7/guided_workflow_gate.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-headless-parity:
	PYTHONPATH=$(CURDIR)/src:$(CURDIR)/exts/isaac_audio_sensors.omni:$(CURDIR)/scripts:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_headless_parity_gate.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/S2/S2.8/parity_gate.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-reliability:
	PYTHONPATH=$(CURDIR)/src:$(CURDIR)/scripts:$${PYTHONPATH} $(PYTHON) scripts/live_reliability_gate.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/S2/S2.9/reliability_gate.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-endurance-capture:
	PYTHONPATH=$(CURDIR)/src:$(CURDIR)/exts/isaac_audio_sensors.omni:$(CURDIR)/scripts:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_endurance_capture_gate.py --minutes 30
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/S2/S2.9/endurance_gate.json').read_text()); ok=data.get('status') == 'passed' and data.get('run_kind') == 'acceptance' and data.get('status_is_acceptance_evidence') is True; sys.exit(0 if ok else 1)"

live-isaac-lab-audio:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_LAB_PYTHON) scripts/live_isaac_lab_audio_smoke.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/isaac_lab_live_smoke.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-isaac-lab-audio-gpu:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_LAB_PYTHON) scripts/live_isaac_lab_audio_smoke.py --require-gpu --perf-budget-ms $(ISAAC_LAB_PERF_BUDGET_MS) --out outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

diagnose-isaac:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) scripts/diagnose_isaac_gpu_audio.py --out-dir $(ISAAC_DIAGNOSTICS_OUT_DIR)

SHOWCASE_LIVE_FLAGS ?=
SHOWCASE_PACKAGE_FLAGS ?=

alex-audio-showcase:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_alex_audio_showcase.py --require-real-alex-v2 $(SHOWCASE_LIVE_FLAGS)
	$(PYTHON) scripts/build_alex_showcase_package.py $(SHOWCASE_PACKAGE_FLAGS)
