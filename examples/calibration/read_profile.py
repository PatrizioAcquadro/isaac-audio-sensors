"""Read a public calibration profile."""

from pathlib import Path

from isaac_audio_sensors.core.io.calibration import read_calibration_profile

path = Path(__file__).with_name("respeaker_xvf3800_nominal.v1.json")
profile = read_calibration_profile(path)
print(profile.profile_id, profile.evidence_status)
