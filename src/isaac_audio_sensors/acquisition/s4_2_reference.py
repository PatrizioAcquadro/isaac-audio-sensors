"""Deterministic, copyright-free S4.2 controlled reference waveform."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import wave
from array import array
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

REFERENCE_FILENAME = "s4_2_reference_v1.0.0.wav"
REFERENCE_VERSION = "1.0.0"
GENERATOR_VERSION = "ias.s4_2.reference_generator.v1"
SAMPLE_RATE_HZ = 48_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
SEED = 0x5A17C4E3

SEGMENTS = (
    ("initial_silence", 1.0),
    ("initial_sync_chirp", 0.25),
    ("alignment_test_separator", 1.0),
    ("seeded_broadband", 5.0),
    ("test_final_separator", 1.0),
    ("final_sync_chirp", 0.25),
    ("final_silence", 1.0),
)

# 129-tap Hamming-windowed 250-6,500 Hz band-pass at 48 kHz, Q30. The
# coefficients are frozen rather than redesigned at generation time so the WAV
# has no NumPy/SciPy or platform-specific filter-design dependency.
_BANDPASS_Q30 = (
    -739981,
    -470671,
    -130578,
    41421,
    -109700,
    -544004,
    -1023540,
    -1241948,
    -1029035,
    -503414,
    -48377,
    -84199,
    -758535,
    -1772188,
    -2507713,
    -2432893,
    -1528985,
    -416116,
    -11827,
    -888087,
    -2762397,
    -4543890,
    -5008798,
    -3707209,
    -1448996,
    80459,
    -561461,
    -3443457,
    -6972037,
    -8807046,
    -7490635,
    -3680752,
    0,
    606156,
    -2991502,
    -8986405,
    -13523499,
    -13237791,
    -7812373,
    -670004,
    2986634,
    -265428,
    -9287302,
    -18525007,
    -21408612,
    -15005734,
    -2730670,
    7148874,
    6765384,
    -5545561,
    -22980110,
    -33728034,
    -28632993,
    -8329375,
    15253120,
    25064238,
    9943136,
    -26061721,
    -62478203,
    -71443416,
    -32973814,
    51868366,
    157901960,
    245646792,
    279620267,
    245646792,
    157901960,
    51868366,
    -32973814,
    -71443416,
    -62478203,
    -26061721,
    9943136,
    25064238,
    15253120,
    -8329375,
    -28632993,
    -33728034,
    -22980110,
    -5545561,
    6765384,
    7148874,
    -2730670,
    -15005734,
    -21408612,
    -18525007,
    -9287302,
    -265428,
    2986634,
    -670004,
    -7812373,
    -13237791,
    -13523499,
    -8986405,
    -2991502,
    606156,
    0,
    -3680752,
    -7490635,
    -8807046,
    -6972037,
    -3443457,
    -561461,
    80459,
    -1448996,
    -3707209,
    -5008798,
    -4543890,
    -2762397,
    -888087,
    -11827,
    -416116,
    -1528985,
    -2432893,
    -2507713,
    -1772188,
    -758535,
    -84199,
    -48377,
    -503414,
    -1029035,
    -1241948,
    -1023540,
    -544004,
    -109700,
    41421,
    -130578,
    -470671,
    -739981,
)


def _xorshift32(state: int) -> int:
    state ^= (state << 13) & 0xFFFFFFFF
    state ^= state >> 17
    state ^= (state << 5) & 0xFFFFFFFF
    return state & 0xFFFFFFFF


def _silence(duration_s: float) -> array[int]:
    return array("h", [0]) * round(duration_s * SAMPLE_RATE_HZ)


def _chirp(duration_s: float = 0.25) -> array[int]:
    count = round(duration_s * SAMPLE_RATE_HZ)
    result = array("h")
    start_hz = 900.0
    end_hz = 3_600.0
    amplitude = 0.30 * 32767.0
    ramp = round(0.02 * SAMPLE_RATE_HZ)
    phase = 0.0
    for index in range(count):
        fraction = index / max(1, count - 1)
        frequency_hz = start_hz + (end_hz - start_hz) * fraction
        phase += 2.0 * math.pi * frequency_hz / SAMPLE_RATE_HZ
        envelope = 1.0
        if index < ramp:
            envelope = 0.5 - 0.5 * math.cos(math.pi * index / ramp)
        elif index >= count - ramp:
            remaining = count - 1 - index
            envelope = 0.5 - 0.5 * math.cos(math.pi * remaining / ramp)
        result.append(round(amplitude * envelope * math.sin(phase)))
    return result


def _seeded_broadband(duration_s: float = 5.0) -> array[int]:
    count = round(duration_s * SAMPLE_RATE_HZ)
    half = len(_BANDPASS_Q30) // 2
    raw_count = count + 2 * half
    state = SEED
    raw: list[int] = []
    for _ in range(raw_count):
        state = _xorshift32(state)
        raw.append(((state >> 16) & 0xFFFF) - 32768)

    result = array("h")
    # The 0.34 scale keeps both broadband RMS and worst-case filter overshoot
    # conservative. All filter math before the final scale is fixed-point.
    for output_index in range(count):
        accumulator = 0
        for tap_index, coefficient in enumerate(_BANDPASS_Q30):
            accumulator += raw[output_index + tap_index] * coefficient
        filtered = accumulator >> 30
        scaled = max(-32767, min(32767, round(filtered * 0.34)))
        result.append(scaled)
    return result


def build_reference_samples() -> array[int]:
    """Return the complete reference as signed native-endian PCM16 samples."""

    samples = array("h")
    samples.extend(_silence(1.0))
    samples.extend(_chirp())
    samples.extend(_silence(1.0))
    samples.extend(_seeded_broadband())
    samples.extend(_silence(1.0))
    samples.extend(_chirp())
    samples.extend(_silence(1.0))
    expected = round(sum(duration for _, duration in SEGMENTS) * SAMPLE_RATE_HZ)
    if len(samples) != expected:
        raise AssertionError(f"reference length {len(samples)} != {expected}")
    return samples


def _pcm_bytes(samples: array[int]) -> bytes:
    return b"".join(struct.pack("<h", sample) for sample in samples)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _segment_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    start_s = 0.0
    for name, duration_s in SEGMENTS:
        records.append(
            {
                "name": name,
                "start_s": start_s,
                "duration_s": duration_s,
                "end_s": start_s + duration_s,
            }
        )
        start_s += duration_s
    return records


def generate_reference(output: str | Path, metadata: str | Path) -> dict[str, Any]:
    """Generate the frozen WAV and its deterministic machine-readable record."""

    output_path = Path(output)
    metadata_path = Path(metadata)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    samples = build_reference_samples()
    pcm = _pcm_bytes(samples)
    with wave.open(str(output_path), "wb") as writer:
        writer.setnchannels(CHANNELS)
        writer.setsampwidth(SAMPLE_WIDTH_BYTES)
        writer.setframerate(SAMPLE_RATE_HZ)
        writer.writeframes(pcm)

    square_sum = sum(sample * sample for sample in samples)
    rms_pcm16 = math.sqrt(square_sum / len(samples))
    peak_pcm16 = max(abs(sample) for sample in samples)
    payload: dict[str, Any] = {
        "schema": "ias.s4_2.reference_wav.v1",
        "filename": REFERENCE_FILENAME,
        "semantic_version": REFERENCE_VERSION,
        "generator_version": GENERATOR_VERSION,
        "deterministic_seed_hex": f"0x{SEED:08X}",
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "channel_count": CHANNELS,
        "bits_per_sample": SAMPLE_WIDTH_BYTES * 8,
        "encoding": "PCM_S16_LE",
        "sample_count": len(samples),
        "duration_s": len(samples) / SAMPLE_RATE_HZ,
        "byte_size": output_path.stat().st_size,
        "rms_pcm16": rms_pcm16,
        "peak_pcm16": peak_pcm16,
        "peak_dbfs": 20.0 * math.log10(peak_pcm16 / 32767.0),
        "sha256": _sha256(output_path),
        "segments": _segment_records(),
        "license": "CC0-1.0",
        "provenance": (
            "Generated entirely by the tracked isaac-audio-sensors S4.2 "
            "generator; no third-party audio is incorporated."
        ),
        "regeneration_command": (
            "PYTHONPATH=src .venv/bin/python "
            "scripts/generate_s4_2_reference_wav.py --output "
            "outputs/isaac_audio_sensors/S4/S4.2/reference/"
            "s4_2_reference_v1.0.0.wav --metadata "
            "outputs/isaac_audio_sensors/S4/S4.2/reference/reference_wav.json"
        ),
        "signal_band_hz": [250, 6500],
        "intentional_clipping": False,
    }
    write_json_atomic(metadata_path, payload)
    return payload


def metadata_json(payload: dict[str, Any]) -> str:
    """Return canonical display JSON for CLI output."""

    return json.dumps(payload, indent=2, sort_keys=True)


__all__ = [
    "CHANNELS",
    "GENERATOR_VERSION",
    "REFERENCE_FILENAME",
    "REFERENCE_VERSION",
    "SAMPLE_RATE_HZ",
    "SEED",
    "SEGMENTS",
    "build_reference_samples",
    "generate_reference",
    "metadata_json",
]
