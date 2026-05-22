VENV_PYTHON := .venv/bin/python
PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python3)
ISAAC_SIM_COMMAND ?= $(PYTHON)
ISAAC_LAB_PYTHON ?= $(PYTHON)
ISAAC_DIAGNOSTICS_OUT_DIR ?= outputs/isaac_audio_sensors/diagnostics
BUILD_FLAGS ?= --no-isolation

.PHONY: test lint format build import-smoke validate-config live-isaac-sim-audio live-isaac-lab-audio diagnose-isaac

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

build:
	$(PYTHON) -m build $(BUILD_FLAGS)

import-smoke:
	$(PYTHON) -c "import isaac_audio_sensors; print(isaac_audio_sensors.__version__)"

validate-config:
	$(PYTHON) -m isaac_audio_sensors.cli validate-config configs/isaac_audio_sensors_phase55.toml

live-isaac-sim-audio:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_SIM_COMMAND) scripts/live_isaac_sim_audio_smoke.py

live-isaac-lab-audio:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(ISAAC_LAB_PYTHON) scripts/live_isaac_lab_audio_smoke.py

diagnose-isaac:
	PYTHONPATH=$(CURDIR)/src:$${PYTHONPATH} $(PYTHON) scripts/diagnose_isaac_gpu_audio.py --out-dir $(ISAAC_DIAGNOSTICS_OUT_DIR)
