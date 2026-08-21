"""Read a public dataset manifest."""

from pathlib import Path

from isaac_audio_sensors.recording import read_dataset_manifest

path = Path(__file__).parents[1] / "manifests" / "minimal_manifest.v1.json"
manifest = read_dataset_manifest(path)
print(manifest.dataset_id, len(manifest.episodes), len(manifest.shards))
