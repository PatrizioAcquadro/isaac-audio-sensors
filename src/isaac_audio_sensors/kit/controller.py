"""Kit UI coordinator and public action facade."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .authoring import AuthoringService
from .configuration import ConfigurationService
from .kit_audio import KitAudioService
from .lifecycle import LifecycleService
from .recording_workflow import RecordingWorkflow
from .replicator_service import ReplicatorService
from .sensor_session import SensorSession
from .state import CurrentStageContext, ExtensionUiState
from .validation import ValidationController


class ExtensionController:
    """Coordinate Kit services and expose stable UI/headless actions."""

    def __init__(
        self,
        *,
        state: ExtensionUiState | None = None,
        stage_context_provider: Callable[[], CurrentStageContext] | None = None,
    ) -> None:
        self.state = state or ExtensionUiState()
        self._validation = ValidationController()
        self.stage_context_provider = stage_context_provider
        self._recording = RecordingWorkflow(self)
        self._kit_audio = KitAudioService(self)
        self._lifecycle = LifecycleService(self)
        self._authoring = AuthoringService(self)
        self._sensor_session = SensorSession(self)
        self._configuration = ConfigurationService(self)
        self._replicator = ReplicatorService(self)

    @property
    def sensor(self) -> Any | None:
        return self._sensor_session.sensor

    @property
    def replicator_recorder(self) -> Any | None:
        return self._replicator.replicator_recorder

    @property
    def ext_id(self) -> str | None:
        return self._lifecycle.ext_id

    @ext_id.setter
    def ext_id(self, value: str | None) -> None:
        self._lifecycle.ext_id = value

    @property
    def window(self) -> Any | None:
        return self._lifecycle.window

    @property
    def ui_available(self) -> bool:
        return self._lifecycle.ui_available

    @property
    def action_status(self) -> str:
        return self._lifecycle.action_status

    @property
    def menu_status(self) -> str:
        return self._lifecycle.menu_status

    @property
    def hotkey_status(self) -> str:
        return self._lifecycle.hotkey_status

    def report_error(self, context: str, exc: BaseException) -> None:
        self._record_error(context, exc)

    def current_stage_context(self) -> CurrentStageContext:
        """Return the current import-safe stage and selection snapshot."""

        return self._authoring._context()

    def handle_window_visibility_changed(self, visible: bool) -> None:
        self._lifecycle._on_window_visibility_changed(visible)

    def latest_waveform_data(self) -> Any | None:
        return self._sensor_session.latest_waveform_data()

    def detach_window_callbacks(self) -> None:
        workflow = vars(self._recording).get("_guided_workflow")
        if workflow is not None:
            workflow.on_change = None

    def refresh_window(self) -> None:
        window = self._lifecycle._ui_window
        if window is not None:
            window.refresh_labels()

    @property
    def guided_workflow(self) -> Any:
        return self._recording.guided_workflow

    def guided_apply_preset(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_apply_preset(*args, **kwargs)

    def guided_validate(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_validate(*args, **kwargs)

    def guided_advance(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_advance(*args, **kwargs)

    def guided_back(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_back(*args, **kwargs)

    @property
    def guided_run_status(self) -> Any:
        return self._recording.guided_run_status

    @property
    def guided_recording_status(self) -> Any:
        return self._recording.guided_recording_status

    @property
    def guided_dataset_validation_report(self) -> Any:
        return self._recording.guided_dataset_validation_report

    @property
    def guided_export_validation_report(self) -> Any:
        return self._recording.guided_export_validation_report

    @property
    def guided_export_status(self) -> Any:
        return self._recording.guided_export_status

    def guided_start_run(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_start_run(*args, **kwargs)

    def guided_stop_run(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_stop_run(*args, **kwargs)

    def guided_inspect_summary(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_inspect_summary(*args, **kwargs)

    def guided_mark_inspected(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_mark_inspected(*args, **kwargs)

    def guided_start_recording(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_start_recording(*args, **kwargs)

    def guided_cancel_recording(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_cancel_recording(*args, **kwargs)

    def guided_stop_recording(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_stop_recording(*args, **kwargs)

    def guided_export(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_export(*args, **kwargs)

    def guided_output_inventory(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_output_inventory(*args, **kwargs)

    def guided_notify_simulator_reset(self, *args: Any, **kwargs: Any) -> Any:
        return self._recording.guided_notify_simulator_reset(*args, **kwargs)

    def on_startup(self, *args: Any, **kwargs: Any) -> Any:
        return self._lifecycle.on_startup(*args, **kwargs)

    def on_shutdown(self, *args: Any, **kwargs: Any) -> Any:
        return self._lifecycle.on_shutdown(*args, **kwargs)

    def build_ui_if_available(self, *args: Any, **kwargs: Any) -> Any:
        return self._lifecycle.build_ui_if_available(*args, **kwargs)

    def show_window(self, *args: Any, **kwargs: Any) -> Any:
        return self._lifecycle.show_window(*args, **kwargs)

    def hide_window(self, *args: Any, **kwargs: Any) -> Any:
        return self._lifecycle.hide_window(*args, **kwargs)

    def toggle_window(self, *args: Any, **kwargs: Any) -> Any:
        return self._lifecycle.toggle_window(*args, **kwargs)

    def is_window_visible(self, *args: Any, **kwargs: Any) -> Any:
        return self._lifecycle.is_window_visible(*args, **kwargs)

    def register_kit_integrations(self, *args: Any, **kwargs: Any) -> Any:
        return self._lifecycle.register_kit_integrations(*args, **kwargs)

    def unregister_kit_integrations(self, *args: Any, **kwargs: Any) -> Any:
        return self._lifecycle.unregister_kit_integrations(*args, **kwargs)

    def refresh_stage_selection(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.refresh_stage_selection(*args, **kwargs)

    def use_selected_as_array(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.use_selected_as_array(*args, **kwargs)

    def use_selected_as_source(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.use_selected_as_source(*args, **kwargs)

    def use_selected_as_object(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.use_selected_as_object(*args, **kwargs)

    def create_demo_object(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.create_demo_object(*args, **kwargs)

    def read_selected_source_transform(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.read_selected_source_transform(*args, **kwargs)

    def read_selected_array_transform(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.read_selected_array_transform(*args, **kwargs)

    def use_selected_as_robot_base(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.use_selected_as_robot_base(*args, **kwargs)

    def author_array(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.author_array(*args, **kwargs)

    def apply_array_pose(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.apply_array_pose(*args, **kwargs)

    def apply_source_position(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.apply_source_position(*args, **kwargs)

    def apply_source_position_preset(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.apply_source_position_preset(*args, **kwargs)

    def select_sound_profile(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.select_sound_profile(*args, **kwargs)

    def auto_select_profile_from_object(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.auto_select_profile_from_object(*args, **kwargs)

    def apply_selected_profile(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.apply_selected_profile(*args, **kwargs)

    def select_rig_profile(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.select_rig_profile(*args, **kwargs)

    def apply_selected_rig_profile(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.apply_selected_rig_profile(*args, **kwargs)

    def author_source(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.author_source(*args, **kwargs)

    def attach_source_to_object(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.attach_source_to_object(*args, **kwargs)

    def detach_source_from_object(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.detach_source_from_object(*args, **kwargs)

    def attach_array_to_object(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.attach_array_to_object(*args, **kwargs)

    def detach_array_from_object(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.detach_array_from_object(*args, **kwargs)

    def refresh_discovery(self, *args: Any, **kwargs: Any) -> Any:
        return self._authoring.refresh_discovery(*args, **kwargs)

    def configure_sensor(self, *args: Any, **kwargs: Any) -> Any:
        return self._sensor_session.configure_sensor(*args, **kwargs)

    def start_sensor(self, *args: Any, **kwargs: Any) -> Any:
        return self._sensor_session.start_sensor(*args, **kwargs)

    def stop_sensor(self, *args: Any, **kwargs: Any) -> Any:
        return self._sensor_session.stop_sensor(*args, **kwargs)

    def play_latest_waveform(self, *args: Any, **kwargs: Any) -> Any:
        return self._sensor_session.play_latest_waveform(*args, **kwargs)

    def stop_audition(self, *args: Any, **kwargs: Any) -> Any:
        return self._sensor_session.stop_audition(*args, **kwargs)

    def activate_kit_listener(self, *args: Any, **kwargs: Any) -> Any:
        return self._kit_audio.activate_listener(*args, **kwargs)

    def restore_previous_kit_listener(self, *args: Any, **kwargs: Any) -> Any:
        return self._kit_audio.restore_listener(*args, **kwargs)

    def start_kit_mix_capture(self, *args: Any, **kwargs: Any) -> Any:
        return self._kit_audio.start_mix_capture(*args, **kwargs)

    def stop_kit_mix_capture(self, *args: Any, **kwargs: Any) -> Any:
        return self._kit_audio.stop_mix_capture(*args, **kwargs)

    def cleanup_kit_audio(self, *args: Any, **kwargs: Any) -> Any:
        return self._kit_audio.cleanup(*args, **kwargs)

    def open_waveform_folder(self, *args: Any, **kwargs: Any) -> Any:
        return self._sensor_session.open_waveform_folder(*args, **kwargs)

    def clear_usd_debug_geometry(self, *args: Any, **kwargs: Any) -> Any:
        return self._sensor_session.clear_usd_debug_geometry(*args, **kwargs)

    def update_sensor(self, *args: Any, **kwargs: Any) -> Any:
        return self._sensor_session.update_sensor(*args, **kwargs)

    def export_latest_frame(self, *args: Any, **kwargs: Any) -> Any:
        return self._sensor_session.export_latest_frame(*args, **kwargs)

    def export_config_summary(self, *args: Any, **kwargs: Any) -> Any:
        return self._configuration.export_config_summary(*args, **kwargs)

    def import_config_summary(self, *args: Any, **kwargs: Any) -> Any:
        return self._configuration.import_config_summary(*args, **kwargs)

    def config_summary_dict(self, *args: Any, **kwargs: Any) -> Any:
        return self._configuration.config_summary_dict(*args, **kwargs)

    def start_replicator(self, *args: Any, **kwargs: Any) -> Any:
        return self._replicator.start_replicator(*args, **kwargs)

    def flush_replicator(self, *args: Any, **kwargs: Any) -> Any:
        return self._replicator.flush_replicator(*args, **kwargs)

    def stop_replicator(self, *args: Any, **kwargs: Any) -> Any:
        return self._replicator.stop_replicator(*args, **kwargs)

    def close_sensor(self, *args: Any, **kwargs: Any) -> Any:
        return self._sensor_session.close_sensor(*args, **kwargs)

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.state.status_message = message
        self.state.error_message = message if error else None
        window = self._lifecycle._ui_window
        if window is not None:
            window.refresh_labels()

    def _record_error(self, context: str, exc: BaseException) -> None:
        self._set_status(f"{context}: {exc}", error=True)
