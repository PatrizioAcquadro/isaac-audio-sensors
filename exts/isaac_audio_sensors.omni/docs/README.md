# Isaac Audio Sensors

`isaac_audio_sensors.omni` provides the Isaac Sim/Kit interface for robot-mounted audio arrays.

Open `Window -> Isaac Audio Sensors` to configure, validate, run, inspect, record, and export sensor output. The archive includes the maintained package plus Auditok, room-acoustics, and FLAC dependencies, and requires no separate installation or runtime download. The standard sensor uses Auditok with the explicit `Activity dBFS` value; safe deterministic presets use `-60`, while arbitrary scenes require application-specific tuning.

The `DOA` control is explicitly off by default. Enabling it selects least-squares for exactly two microphones or PyRoom SRP for supported planar arrays; the bundled archive contains the required PyRoom runtime and never falls back between estimators.

Source and documentation: <https://github.com/PatrizioAcquadro/isaac-audio-sensors>
