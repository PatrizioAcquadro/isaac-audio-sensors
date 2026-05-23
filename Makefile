VENV_PYTHON := .venv/bin/python
PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python3)
ISAAC_SIM_COMMAND ?= $(PYTHON)
ISAAC_LAB_PYTHON ?= $(PYTHON)
ISAAC_DIAGNOSTICS_OUT_DIR ?= outputs/isaac_audio_sensors/diagnostics
BUILD_FLAGS ?= --no-isolation

.PHONY: test lint format build audit-dist import-smoke validate-config export-schema live-isaac-sim-audio live-isaac-lab-audio live-isaac-lab-audio-gpu diagnose-isaac

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

build:
	$(PYTHON) -m build $(BUILD_FLAGS)
	$(PYTHON) scripts/audit_distribution.py --dist-dir dist

audit-dist:
	$(PYTHON) scripts/audit_distribution.py --dist-dir dist

import-smoke:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -c "import isaac_audio_sensors; print(isaac_audio_sensors.__version__)"

validate-config:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors.cli validate-config configs/isaac_audio_sensors_demo.toml

export-schema:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) -m isaac_audio_sensors.cli export-schema --out docs/schemas/audio_sensor_frame.v1.schema.json

live-isaac-sim-audio:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_isaac_sim_audio_smoke.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/isaac_sim_live_smoke.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-isaac-lab-audio:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_LAB_PYTHON) scripts/live_isaac_lab_audio_smoke.py
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/isaac_lab_live_smoke.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

live-isaac-lab-audio-gpu:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_LAB_PYTHON) scripts/live_isaac_lab_audio_smoke.py --require-gpu --out outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json
	$(PYTHON) -c "import json, pathlib, sys; data=json.loads(pathlib.Path('outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json').read_text()); sys.exit(0 if data.get('status') == 'passed' else 1)"

diagnose-isaac:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) scripts/diagnose_isaac_gpu_audio.py --out-dir $(ISAAC_DIAGNOSTICS_OUT_DIR)
