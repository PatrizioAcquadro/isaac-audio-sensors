VENV_PYTHON := .venv/bin/python
PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python3)
ISAAC_SIM_COMMAND ?= $(PYTHON)
ISAAC_LAB_PYTHON ?= $(PYTHON)
ISAAC_DIAGNOSTICS_OUT_DIR ?= outputs/isaac_audio_sensors/diagnostics
BUILD_FLAGS ?= --no-isolation
EXPECTED_VERSION ?= 1.5.0

.PHONY: test lint format build audit-dist import-smoke validate-config export-schema regenerate-traces live-evidence-report live-isaac-sim-audio live-isaac-occlusion live-omniverse-extension-ux live-omniverse-extension-ux-screenshots live-isaac-lab-audio live-isaac-lab-audio-gpu diagnose-isaac

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

build:
	$(PYTHON) -c "import shutil; from pathlib import Path; shutil.rmtree('dist', ignore_errors=True); Path('dist').mkdir()"
	$(PYTHON) -m build $(BUILD_FLAGS)
	$(PYTHON) scripts/audit_distribution.py --dist-dir dist

audit-dist:
	$(PYTHON) scripts/audit_distribution.py --dist-dir dist

import-smoke:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -c "import isaac_audio_sensors, sys; print(isaac_audio_sensors.__version__); sys.exit(0 if isaac_audio_sensors.__version__ == '$(EXPECTED_VERSION)' else 1)"

validate-config:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors.cli validate-config configs/isaac_audio_sensors_demo.toml

export-schema:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors.cli export-schema --out docs/schemas/audio_sensor_frame.v1.schema.json

regenerate-traces:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) scripts/regenerate_example_traces.py

live-evidence-report:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) scripts/generate_live_evidence_report.py

live-isaac-sim-audio:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_isaac_sim_audio_smoke.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/isaac_sim_live_smoke.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-isaac-occlusion:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_isaac_occlusion_gate.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/isaac_occlusion_live_gate.json').read_text()); ok=data.get('status') == 'passed' and data.get('screenshot', {}).get('status') == 'captured' and pathlib.Path(data['screenshot']['path']).is_file(); sys.exit(0 if ok else 1)"

live-omniverse-extension-ux:
	PYTHONPATH=$(CURDIR)/src:$(CURDIR)/exts/isaac_audio_sensors.omni:$(CURDIR)/scripts:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_omniverse_extension_ux.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/omniverse_extension_live_ux.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-omniverse-extension-ux-screenshots:
	PYTHONPATH=$(CURDIR)/src:$(CURDIR)/exts/isaac_audio_sensors.omni:$(CURDIR)/scripts:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_omniverse_extension_ux.py --require-screenshot
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/omniverse_extension_live_ux.json').read_text()); scenarios=data.get('object_attach_live_qa', {}); required=('generic_scene','molmo_floorplan1'); instruments=data.get('instruments', {}); ok=data.get('status') == 'passed' and instruments.get('status') == 'passed' and instruments.get('compass', {}).get('needle_count', 0) > 0 and instruments.get('meters') and instruments.get('panel', {}).get('status') == 'captured' and pathlib.Path(instruments.get('panel', {}).get('path', '')).is_file() and all(scenarios.get(name, {}).get('screenshot', {}).get('status') == 'captured' and pathlib.Path(scenarios[name]['screenshot']['path']).is_file() for name in required); sys.exit(0 if ok else 1)"

live-isaac-lab-audio:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_LAB_PYTHON) scripts/live_isaac_lab_audio_smoke.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/isaac_lab_live_smoke.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-isaac-lab-audio-gpu:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_LAB_PYTHON) scripts/live_isaac_lab_audio_smoke.py --require-gpu --out outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

diagnose-isaac:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) scripts/diagnose_isaac_gpu_audio.py --out-dir $(ISAAC_DIAGNOSTICS_OUT_DIR)
