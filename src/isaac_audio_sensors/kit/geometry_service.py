"""Controller-owned prepared scene shared by authoring and live sensing."""

from pathlib import Path

from isaac_audio_sensors.isaac.acoustic_scene import AcousticSceneSession
from isaac_audio_sensors.isaac.acoustic_scene._nlos import NLOSScene
from isaac_audio_sensors.isaac.acoustic_scene._pra import Transport
from isaac_audio_sensors.isaac.acoustic_scene._specular import SpecularScene

from ._service import ControllerService
from .geometry_settings import config_from_state
from .validation.results import ValidationFinding, ValidationReport


class GeometryService(ControllerService):
    def __init__(self, host):
        super().__init__(host)
        self.session = None
        self.verified_config = None

    def prepare(self, stage, roots=None):
        roots = tuple(roots or self.state.geometry_roots.split()) or ("/",)
        if (
            self.session is None
            or self.session.closed
            or (self.session.stage is not stage or self.session.roots != roots)
        ):
            self.close()
            self.session = AcousticSceneSession(stage, roots)
        self.state.geometry_roots = " ".join(roots) if roots != ("/",) else ""
        self.session.refresh()
        return self.session

    def close(self):
        # Producers borrow the scene's native handles.
        try:
            self._host.close_sensor()
        finally:
            try:
                if self.session is not None:
                    self.session.close()
            finally:
                self.session = None
                self.verified_config = None

    def verify_scene(self, library):
        self._host.close_sensor()
        self.verified_config = None
        if self.session is None:
            raise ValueError("Import the acoustic scene first.")
        return self.session.verify_provider(library)

    def sensor_inputs(self, stage):
        config = config_from_state(self.state)
        session = self.prepare(stage)
        if session.issues:
            raise ValueError(
                f"Correct Acoustic Scene issues before Configure: {session.issues}"
            )
        provider = session.provider
        if (
            provider is None
            or Path(provider.library_path) != Path(config.library_path).resolve()
        ):
            self.verify_scene(config.library_path)
        if self.verified_config != (config, self.state.sample_rate_hz):
            self.verified_config = None
            specular = SpecularScene(
                session,
                config.specular_library_path,
                self.state.sample_rate_hz,
                config.reflection_order,
                343.0,
                config.max_image_candidates,
            )
            nlos = None
            try:
                if config.diffuse is not None:
                    Transport(specular)
                if config.nlos is not None:
                    nlos = NLOSScene(session, config.nlos)
                    nlos.refresh(0.0)
            finally:
                if nlos is not None:
                    nlos.close()
                specular.close()
            self.verified_config = (config, self.state.sample_rate_hz)
        return dict(
            acoustic_scene=session,
            geometry_config=config,
            occlusion_enabled=False,
            analytic_max_order=0,
            analytic_air_absorption=False,
            analytic_ray_tracing=False,
        )

    def validate(self, stage):
        try:
            self.sensor_inputs(stage)
        except Exception as exc:
            return ValidationReport(
                (
                    ValidationFinding(
                        "geometry_available",
                        "error",
                        str(self.explain(exc)),
                        "geometry_library_path",
                    ),
                )
            )
        return ValidationReport()

    @staticmethod
    def explain(exc):
        message = str(exc)
        if "coverage" in message or "probes" in message:
            message += (
                " Check Acoustic Scene roots, floor geometry, source/microphone "
                "height and NLOS probe spacing/height; then Configure again."
            )
        elif "ABI" in message or "undefined symbol" in message:
            message += " Rebuild the selected native bridge with the maintained recipe."
        return RuntimeError(message)

    def status_text(self):
        session = self.session
        if session is None or session.closed:
            return "Scene not prepared. Import the acoustic scene."
        summary = session.summary()
        status = "Provider verified" if self.verified_config else summary["state"]
        diagnostic = self.state.latest_geometry_diagnostics
        sensor = self._host.sensor
        if (
            self.state.latest_frame is not None
            and sensor is not None
            and sensor.latest_signal_block is not None
            and sensor.latest_signal_block.producer_id == "geometry_acoustics"
        ):
            status = "PCM active: " + diagnostic.get(
                "domain", "Geometry (diagnostics off)"
            )
        parts = [
            f"{status}. {summary['objects']} objects; "
            f"{summary['fallback_materials']} material defaults."
        ]
        parts.extend(str(v) for v in (*summary["issues"], *summary["warnings"]))
        if nlos := diagnostic.get("nlos"):
            parts.append(
                f"NLOS: {nlos['probes']} probes; {nlos['bakes']} bakes; "
                f"coverage {nlos['coverage']}."
            )
            parts.append("No selected route does not establish physical silence.")
        if diffuse := diagnostic.get("diffuse"):
            parts.extend(diffuse.get("limits", ()))
        if (
            self.state.backend == "geometry_acoustics"
            and self._host.sensor is not None
            and self._host.sensor.geometry_config != config_from_state(self.state)
        ):
            parts.append("Settings changed: Configure to apply and reset the stream.")
        return "\n".join(parts)
