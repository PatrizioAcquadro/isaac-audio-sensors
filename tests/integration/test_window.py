"""Omni UI host adapter smoke test."""

import sys
from types import ModuleType

from isaac_audio_sensors.core.directivity import DirectivityPattern
from isaac_audio_sensors.kit import ExtensionController
from tests.kit_helpers import _FakeUI


def test_kit_window_builds_and_refreshes(monkeypatch) -> None:
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    controller = ExtensionController()

    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    assert window is not None
    assert controller.ui_available is True

    controller.state.status_message = "Host refresh complete"
    controller.refresh_window()

    assert window._labels["status"].text == "Host refresh complete"

    directivity_widget, choices = window._combo_fields["source_directivity"]
    assert choices == ("omni", "cardioid", "supercardioid", "figure_eight")
    directivity_widget.model.set_value(3)
    assert controller.state.source_directivity is DirectivityPattern.FIGURE_EIGHT

    _, environment_choices = window._combo_fields["environment_resolution_mode"]
    assert environment_choices == (
        "unconfigured",
        "manual_free_field",
        "anchor",
        "auto",
    )
