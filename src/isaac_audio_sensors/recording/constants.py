"""Dataset manifest contract constants."""

DATASET_MANIFEST_SCHEMA_VERSION = "ias.audio_dataset_manifest.v2"

DATASET_MANIFEST_UNITS = {
    "position": "m",
    "orientation": "quaternion_xyzw",
    "time": "s",
    "timestamp": "ms",
    "sample_rate": "Hz",
}
