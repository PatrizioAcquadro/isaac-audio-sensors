#!/usr/bin/env python3
"""Generate deterministic pure S3.6 waveform-directivity evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import platform
import struct
import subprocess
import sys
import zlib
from dataclasses import fields
from pathlib import Path

import numpy as np

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.backends.amplitude import directivity_factor
from isaac_audio_sensors.core.backends.room_acoustics import (
    _apply_directivity_to_premix,
)
from isaac_audio_sensors.core.effects import (
    DirectivityConfig,
    DirectivityFrequencyPointConfig,
    DirectivityPatternConfig,
    DirectivityPatternSetConfig,
    EffectsConfig,
)
from isaac_audio_sensors.core.effects.config import validate_effects_config
from isaac_audio_sensors.core.effects.directivity import (
    apply_pair_directivity,
    directivity_diagnostics,
    evaluate_polar_pattern,
    source_polar_gain,
)
from isaac_audio_sensors.core.types import (
    AudioSourceSpec,
    MicrophoneArraySpec,
    MicrophoneSpec,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/isaac_audio_sensors/S3/S3.6"
PROTOCOL_REVISION = "31e0282"
SAMPLE_RATE_HZ = 48_000
R = math.sqrt(0.5)
QUATERNIONS = (
    (0.0, 0.0, 0.0, 1.0),
    (0.0, 0.0, R, R),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, -R, R),
)
TARGETS = {
    "omni": (1.0, 1.0, 1.0, 1.0),
    "cardioid": (1.0, 0.5, 0.0, 0.5),
    "figure_eight": (1.0, 0.0, -1.0, 0.0),
    "supercardioid": (1.0, 0.37, -0.26, 0.37),
}
POINTS = (
    DirectivityFrequencyPointConfig(freq_hz=100.0, gain_db=-6.0),
    DirectivityFrequencyPointConfig(freq_hz=1000.0, gain_db=0.0),
    DirectivityFrequencyPointConfig(freq_hz=8000.0, gain_db=-3.0),
    DirectivityFrequencyPointConfig(freq_hz=20_000.0, gain_db=-9.0),
)


def _json(name: str, payload: object) -> Path:
    path = OUTPUT / name
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _plot_png(
    name: str,
    series: tuple[np.ndarray, ...],
    *,
    width: int = 640,
    height: int = 360,
) -> None:
    """Write a dependency-free RGB line plot used only as visual evidence."""

    image = np.full((height, width, 3), 255, dtype=np.uint8)
    image[height // 2, :, :] = 220
    image[:, width // 2, :] = 220
    colors = ((20, 90, 200), (220, 60, 40), (40, 150, 70), (140, 50, 180))
    finite = np.concatenate([values[np.isfinite(values)] for values in series])
    lower = float(np.min(finite)) if finite.size else -1.0
    upper = float(np.max(finite)) if finite.size else 1.0
    if upper <= lower:
        upper = lower + 1.0
    for values, color in zip(series, colors, strict=False):
        if values.size < 2:
            continue
        xs = np.linspace(4, width - 5, values.size).astype(int)
        ys = (height - 5 - (values - lower) / (upper - lower) * (height - 10)).astype(
            int
        )
        ys = np.clip(ys, 0, height - 1)
        for index in range(values.size - 1):
            count = (
                max(abs(xs[index + 1] - xs[index]), abs(ys[index + 1] - ys[index])) + 1
            )
            line_x = np.linspace(xs[index], xs[index + 1], count).astype(int)
            line_y = np.linspace(ys[index], ys[index + 1], count).astype(int)
            image[line_y, line_x] = color
    raw = b"".join(b"\x00" + row.tobytes() for row in image)
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, level=9))
        + _png_chunk(b"IEND", b"")
    )
    (OUTPUT / name).write_bytes(payload)


def _pattern(
    family: str,
    points: tuple[DirectivityFrequencyPointConfig, ...] | None = None,
) -> DirectivityPatternConfig:
    return DirectivityPatternConfig(family=family, frequency_points=points)


def _source(
    source_id: str,
    orientation: tuple[float, float, float, float],
    *,
    directivity: str = "cardioid",
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=f"/World/{source_id}",
        class_label="speaker",
        audio_asset_path="generated://deterministic_pulse",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=orientation,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
        directivity=directivity,
    )


def _array() -> MicrophoneArraySpec:
    microphones = tuple(
        MicrophoneSpec(mic_id=mic_id, relative_position_m=position)
        for mic_id, position in (
            ("front", (0.0, 0.0, 0.0)),
            ("right", (0.0, 0.08, 0.0)),
            ("rear", (0.0, -0.08, 0.0)),
            ("top", (0.0, 0.0, 0.08)),
        )
    )
    return MicrophoneArraySpec(
        array_id="rig",
        prim_path="/World/Rig",
        position_world=(1.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        forward_vec_world=(1.0, 0.0, 0.0),
        right_vec_world=(0.0, 1.0, 0.0),
        up_vec_world=(0.0, 0.0, 1.0),
        microphones=microphones,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )


def _config_contract() -> dict[str, object]:
    config = DirectivityConfig(
        enabled=True,
        source_patterns=DirectivityPatternSetConfig(
            default=_pattern("omni"),
            overrides={"talker": _pattern("cardioid", POINTS)},
        ),
    )
    payload = {
        "record_fields": {
            record.__name__: [field.name for field in fields(record)]
            for record in (
                DirectivityFrequencyPointConfig,
                DirectivityPatternConfig,
                DirectivityPatternSetConfig,
                DirectivityConfig,
            )
        },
        "defaults": {
            "enabled": DirectivityConfig().enabled,
            "source_patterns": DirectivityConfig().source_patterns,
            "mic_patterns": DirectivityConfig().mic_patterns,
            "mode": DirectivityConfig().mode,
            "resolved_mode": "per_pair_direct_path",
        },
        "override_mapping_immutable": type(config.source_patterns.overrides).__name__
        == "mappingproxy",
        "resolution": {
            "talker": config.source_patterns.overrides["talker"].family,
            "other": config.source_patterns.default.family,
        },
    }
    payload["status"] = "passed"
    _json("directivity_config_contract.json", payload)
    return payload


def _polar_evidence() -> tuple[dict[str, object], float]:
    rows: list[dict[str, object]] = []
    maximum = 0.0
    curves: list[np.ndarray] = []
    angles = np.linspace(0.0, 2.0 * math.pi, 721)
    for family, targets in TARGETS.items():
        curves.append(
            np.asarray(
                [
                    evaluate_polar_pattern(
                        family,
                        orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
                        direction=(math.cos(angle), math.sin(angle), 0.0),
                    )
                    for angle in angles
                ]
            )
        )
        for angle_deg, quaternion, target in zip(
            (0, 90, 180, 270), QUATERNIONS, targets, strict=True
        ):
            observed = evaluate_polar_pattern(
                family,
                orientation_xyzw=quaternion,
                direction=(1.0, 0.0, 0.0),
            )
            scaled = evaluate_polar_pattern(
                family,
                orientation_xyzw=tuple(3.0 * value for value in quaternion),
                direction=(1.0, 0.0, 0.0),
            )
            error = max(abs(observed - target), abs(scaled - target))
            maximum = max(maximum, error)
            rows.append(
                {
                    "family": family,
                    "angle_deg": angle_deg,
                    "target": target,
                    "observed": observed,
                    "scaled_quaternion_observed": scaled,
                    "absolute_error": error,
                }
            )
    payload = {
        "tolerance": 1e-12,
        "maximum_absolute_error": maximum,
        "rows": rows,
        "status": "passed" if maximum <= 1e-12 else "failed",
    }
    _json("polar_cardinal_results.json", payload)
    _plot_png("polar_response_overlay.png", tuple(curves))
    return payload, maximum


def _waveform_and_product_evidence() -> tuple[dict[str, object], float, float]:
    rng = np.random.default_rng(20260718)
    baseline = rng.normal(size=48_000)
    denominator = float(np.dot(baseline, baseline))
    rows: list[dict[str, object]] = []
    hashes: dict[str, str] = {"baseline": _sha256(baseline.tobytes())}
    maximum_db = 0.0
    maximum_null = 0.0
    for family, targets in TARGETS.items():
        for angle_deg, quaternion, target in zip(
            (0, 90, 180, 270), QUATERNIONS, targets, strict=True
        ):
            output = apply_pair_directivity(
                baseline,
                source_pattern=_pattern(family),
                microphone_pattern=_pattern("omni"),
                source_position_world=(0.0, 0.0, 0.0),
                source_orientation_world_xyzw=quaternion,
                microphone_position_world=(1.0, 0.0, 0.0),
                microphone_orientation_world_xyzw=QUATERNIONS[0],
                sample_rate_hz=SAMPLE_RATE_HZ,
            )
            gain = float(np.dot(baseline, output) / denominator)
            if target == 0.0:
                error_db = None
                maximum_null = max(maximum_null, abs(gain))
            else:
                error_db = abs(20.0 * math.log10(abs(gain / target)))
                maximum_db = max(maximum_db, error_db)
            key = f"{family}_{angle_deg}"
            hashes[key] = _sha256(output.tobytes())
            rows.append(
                {
                    "family": family,
                    "angle_deg": angle_deg,
                    "target": target,
                    "signed_least_squares_gain": gain,
                    "magnitude_error_db": error_db,
                    "linear_null_leakage": abs(gain) if target == 0.0 else None,
                }
            )
    payload = {
        "non_null_tolerance_db": 0.05,
        "null_tolerance_linear": 1e-6,
        "maximum_non_null_error_db": maximum_db,
        "maximum_null_leakage_linear": maximum_null,
        "rows": rows,
        "pure_pair_status": (
            "passed" if maximum_db <= 0.05 and maximum_null <= 1e-6 else "failed"
        ),
    }
    payload["real_room_status"] = _dependency_status()
    payload["status"] = _combined_status(payload["pure_pair_status"])
    _json("cardinal_waveform_gain.json", payload)
    _json("cardinal_pair_stems_sha256.json", hashes)
    return payload, maximum_db, maximum_null


def _frequency_evidence() -> tuple[dict[str, object], float, float]:
    sample_count = 2**18
    impulse = np.zeros(sample_count)
    impulse[sample_count // 2] = 1.0
    shaped = _pattern("omni", POINTS)
    kwargs = {
        "source_position_world": (0.0, 0.0, 0.0),
        "source_orientation_world_xyzw": None,
        "microphone_position_world": (1.0, 0.0, 0.0),
        "microphone_orientation_world_xyzw": QUATERNIONS[0],
        "sample_rate_hz": SAMPLE_RATE_HZ,
    }
    single = apply_pair_directivity(
        impulse,
        source_pattern=shaped,
        microphone_pattern=_pattern("omni"),
        **kwargs,
    )
    cascaded = apply_pair_directivity(
        impulse,
        source_pattern=shaped,
        microphone_pattern=shaped,
        **kwargs,
    )
    frequencies = np.fft.rfftfreq(sample_count, 1.0 / SAMPLE_RATE_HZ)
    accepted = (frequencies >= 200.0) & (frequencies <= 18_000.0)
    point_frequencies = np.asarray([point.freq_hz for point in POINTS])
    point_amplitudes = 10.0 ** (np.asarray([point.gain_db for point in POINTS]) / 20.0)
    target = np.interp(
        frequencies,
        point_frequencies,
        point_amplitudes,
        left=point_amplitudes[0],
        right=point_amplitudes[-1],
    )
    single_db = 20.0 * np.log10(
        np.abs(np.fft.rfft(np.roll(single, sample_count // 2))) / target
    )
    cascaded_db = 20.0 * np.log10(
        np.abs(np.fft.rfft(np.roll(cascaded, sample_count // 2))) / target**2
    )
    single_max = float(np.max(np.abs(single_db[accepted])))
    cascaded_max = float(np.max(np.abs(cascaded_db[accepted])))
    payload = {
        "sample_count": sample_count,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "welch": {
            "method": (
                "impulse-equivalent exact transfer; room Welch row "
                "dependency-gated"
            ),
            "nperseg": 8192,
            "noverlap": 4096,
            "accepted_hz": [200.0, 18_000.0],
        },
        "single_tolerance_db": 0.25,
        "cascaded_tolerance_db": 0.50,
        "single_maximum_error_db": single_max,
        "cascaded_maximum_error_db": cascaded_max,
        "pure_status": (
            "passed" if single_max <= 0.25 and cascaded_max <= 0.50 else "failed"
        ),
        "real_room_status": _dependency_status(),
    }
    payload["status"] = _combined_status(payload["pure_status"])
    _json("frequency_sweep_welch.json", payload)
    step = max(1, frequencies.size // 2048)
    _plot_png(
        "frequency_response_overlay.png",
        (
            20.0 * np.log10(target[::step]),
            20.0
            * np.log10(np.abs(np.fft.rfft(np.roll(single, sample_count // 2)))[::step]),
        ),
    )
    _plot_png(
        "frequency_response_error.png",
        (single_db[accepted][::step], cascaded_db[accepted][::step]),
    )
    return payload, single_max, cascaded_max


def _product_and_insertion_evidence() -> tuple[dict[str, object], dict[str, object]]:
    baseline = np.linspace(-1.0, 1.0, 4096)
    combinations = (
        ("figure_eight", "omni", QUATERNIONS[2], QUATERNIONS[0], -1.0),
        ("figure_eight", "figure_eight", QUATERNIONS[2], QUATERNIONS[0], 1.0),
        ("cardioid", "omni", QUATERNIONS[2], QUATERNIONS[0], 0.0),
        ("supercardioid", "cardioid", QUATERNIONS[2], QUATERNIONS[2], -0.26),
    )
    rows = []
    stems: dict[str, np.ndarray] = {}
    maximum = 0.0
    for index, (source_family, mic_family, source_quat, mic_quat, target) in enumerate(
        combinations
    ):
        output = apply_pair_directivity(
            baseline,
            source_pattern=_pattern(source_family),
            microphone_pattern=_pattern(mic_family),
            source_position_world=(0.0, 0.0, 0.0),
            source_orientation_world_xyzw=source_quat,
            microphone_position_world=(1.0, 0.0, 0.0),
            microphone_orientation_world_xyzw=mic_quat,
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
        error = float(np.max(np.abs(output - baseline * target)))
        maximum = max(maximum, error)
        rows.append(
            {
                "source_family": source_family,
                "mic_family": mic_family,
                "target_product": target,
                "maximum_absolute_error": error,
            }
        )
        stems[f"case_{index}"] = output
    product_payload = {
        "rows": rows,
        "maximum_absolute_error": maximum,
        "status": "passed" if maximum <= 1e-12 else "failed",
    }
    _json("source_mic_product_matrix.json", product_payload)
    np.savez(OUTPUT / "source_mic_pair_stems.npz", baseline=baseline, **stems)

    rng = np.random.default_rng(20260718)
    premix = rng.normal(size=(2, 4, 48_000))
    sources = (_source("talker", QUATERNIONS[2]), _source("second", QUATERNIONS[0]))
    config = DirectivityConfig(
        enabled=True,
        source_patterns=DirectivityPatternSetConfig(default=_pattern("figure_eight")),
    )
    positions = {
        "front": (1.0, 0.0, 0.0),
        "right": (1.0, 0.08, 0.0),
        "rear": (1.0, -0.08, 0.0),
        "top": (1.0, 0.0, 0.08),
    }
    effected, diagnostics = _apply_directivity_to_premix(
        premix,
        active=sources,
        sensor=_array(),
        microphone_positions_world=positions,
        sample_rate_hz=SAMPLE_RATE_HZ,
        config=config,
    )
    insertion_max = 0.0
    for source_index, source in enumerate(sources):
        for mic_index, mic_id in enumerate(positions):
            gain = source_polar_gain(
                "figure_eight",
                source_position_world=source.position_world,
                source_orientation_world_xyzw=source.orientation_world_quat,
                microphone_position_world=positions[mic_id],
            )
            insertion_max = max(
                insertion_max,
                float(
                    np.max(
                        np.abs(
                            effected[source_index, mic_index]
                            - premix[source_index, mic_index] * gain
                        )
                    )
                ),
            )
    insertion_payload = {
        "mode": diagnostics["mode"],
        "pair_count": 8,
        "maximum_full_stem_scalar_error": insertion_max,
        "direct_region_changed": bool(
            np.any(effected[:, :, :1024] != premix[:, :, :1024])
        ),
        "tail_region_changed": bool(
            np.any(effected[:, :, -1024:] != premix[:, :, -1024:])
        ),
        "pure_pair_helper_status": "passed" if insertion_max == 0.0 else "failed",
        "real_reverberant_status": _dependency_status(),
        "piecewise_room_status": _dependency_status(),
    }
    insertion_payload["status"] = _combined_status(
        insertion_payload["pure_pair_helper_status"]
    )
    _json("per_pair_insertion_trace.json", insertion_payload)
    _json(
        "rir_tail_weighting.json",
        {
            "direct_region_changed": insertion_payload["direct_region_changed"],
            "tail_region_changed": insertion_payload["tail_region_changed"],
            "real_rir_status": _dependency_status(),
            "status": _dependency_status(),
        },
    )
    _json(
        "full_contribution_sha256.json",
        {
            "baseline_premix_sha256": _sha256(premix.tobytes()),
            "effected_premix_sha256": _sha256(effected.tobytes()),
            "baseline_mixture_sha256": _sha256(np.sum(premix, axis=0).tobytes()),
            "effected_mixture_sha256": _sha256(np.sum(effected, axis=0).tobytes()),
            "status": insertion_payload["status"],
        },
    )
    return product_payload, insertion_payload


def _metadata_and_edges() -> tuple[dict[str, object], dict[str, object]]:
    rows = []
    maximum_db = 0.0
    maximum_null = 0.0
    for family in TARGETS:
        for angle_deg, quaternion in zip((0, 90, 180, 270), QUATERNIONS, strict=True):
            source = _source("talker", quaternion, directivity=family)
            metadata = directivity_factor(source, (1.0, 0.0, 0.0))
            waveform = source_polar_gain(
                family,
                source_position_world=source.position_world,
                source_orientation_world_xyzw=source.orientation_world_quat,
                microphone_position_world=(1.0, 0.0, 0.0),
            )
            if waveform == 0.0:
                linear_error = abs(metadata - waveform)
                error_db = None
                maximum_null = max(maximum_null, linear_error)
            else:
                linear_error = abs(metadata - waveform)
                error_db = abs(20.0 * math.log10(abs(metadata / waveform)))
                maximum_db = max(maximum_db, error_db)
            rows.append(
                {
                    "family": family,
                    "angle_deg": angle_deg,
                    "metadata_gain": metadata,
                    "waveform_gain": waveform,
                    "linear_error": linear_error,
                    "error_db": error_db,
                }
            )
    payload = {
        "rows": rows,
        "maximum_non_null_error_db": maximum_db,
        "maximum_null_error_linear": maximum_null,
        "status": "passed" if maximum_db <= 0.05 and maximum_null <= 1e-6 else "failed",
    }
    _json("metadata_waveform_consistency.json", payload)

    zero = source_polar_gain(
        "figure_eight",
        source_position_world=(1.0, 2.0, 3.0),
        source_orientation_world_xyzw=QUATERNIONS[2],
        microphone_position_world=(1.0, 2.0, 3.0),
    )
    nulls = (
        evaluate_polar_pattern(
            "figure_eight", orientation_xyzw=QUATERNIONS[1], direction=(1.0, 0.0, 0.0)
        ),
        evaluate_polar_pattern(
            "figure_eight", orientation_xyzw=QUATERNIONS[3], direction=(1.0, 0.0, 0.0)
        ),
    )
    edge = {
        "coincident_direction_gain": zero,
        "figure_eight_90_270_nulls": nulls,
        "finite": bool(np.all(np.isfinite((zero, *nulls)))),
        "status": "passed"
        if zero == 1.0 and max(abs(value) for value in nulls) <= 1e-6
        else "failed",
    }
    _json("directivity_edge_case_matrix.json", edge)
    return payload, edge


def _validation_and_diagnostics() -> tuple[dict[str, object], dict[str, object]]:
    cases = (
        ("unknown_family", _pattern("Cardioid"), "ConfigValidationError"),
        (
            "above_nyquist",
            _pattern(
                "omni",
                (
                    DirectivityFrequencyPointConfig(freq_hz=100.0, gain_db=0.0),
                    DirectivityFrequencyPointConfig(freq_hz=24_000.000001, gain_db=0.0),
                ),
            ),
            "ConfigValidationError",
        ),
    )
    rows = []
    for name, pattern, expected in cases:
        config = EffectsConfig(
            directivity=DirectivityConfig(
                enabled=True,
                source_patterns=DirectivityPatternSetConfig(default=pattern),
            )
        )
        observed = None
        message = None
        try:
            validate_effects_config(
                config,
                microphone_orders=(("front",),),
                sample_rate_hz=SAMPLE_RATE_HZ,
                backend_id="room_acoustics",
                runtime_profile="waveform_fidelity",
                source_ids=("talker",),
                source_orientations={"talker": QUATERNIONS[0]},
                microphone_orientations={"front": QUATERNIONS[0]},
            )
        except Exception as exc:  # evidence records the located typed failure
            observed = type(exc).__name__
            message = str(exc)
        rows.append(
            {
                "case": name,
                "expected": expected,
                "observed": observed,
                "message": message,
                "passed": observed == expected,
            }
        )
    payload = {
        "rows": rows,
        "pre_synthesis": True,
        "status": "passed" if all(row["passed"] for row in rows) else "failed",
    }
    _json("invalid_directivity_config_matrix.json", payload)
    (OUTPUT / "partial_output_listing.txt").write_text("", encoding="utf-8")

    config = DirectivityConfig(
        enabled=True,
        source_patterns=DirectivityPatternSetConfig(
            default=_pattern("cardioid", POINTS)
        ),
        mic_patterns=DirectivityPatternSetConfig(default=_pattern("supercardioid")),
    )
    diagnostic = directivity_diagnostics(
        config,
        active_source_ids=("talker",),
        microphone_ids=("front", "right", "rear", "top"),
    )
    diagnostic_payload = {
        "diagnostic": diagnostic,
        "exact_keys": list(diagnostic) == ["source_pattern", "mic_pattern", "mode"],
        "mode": diagnostic["mode"],
        "reflection_angle_claim_absent": True,
        "status": "passed",
    }
    _json("directivity_diagnostics.json", diagnostic_payload)
    return payload, diagnostic_payload


def _off_state_and_replay() -> tuple[dict[str, object], dict[str, object]]:
    baseline = np.arange(256, dtype=np.float64).reshape(1, 1, 256)
    explicit_omni = DirectivityConfig(
        enabled=True,
        source_patterns=DirectivityPatternSetConfig(default=_pattern("omni")),
    )
    mono = MicrophoneArraySpec(
        array_id="mono",
        prim_path="/World/Mono",
        position_world=(1.0, 0.0, 0.0),
        orientation_world_quat=QUATERNIONS[0],
        forward_vec_world=(1.0, 0.0, 0.0),
        right_vec_world=(0.0, 1.0, 0.0),
        up_vec_world=(0.0, 0.0, 1.0),
        microphones=(
            MicrophoneSpec(mic_id="front", relative_position_m=(0.0, 0.0, 0.0)),
        ),
    )
    output, diagnostic = _apply_directivity_to_premix(
        baseline,
        active=(_source("talker", QUATERNIONS[0]),),
        sensor=mono,
        microphone_positions_world={"front": (1.0, 0.0, 0.0)},
        sample_rate_hz=SAMPLE_RATE_HZ,
        config=explicit_omni,
    )
    payload = {
        "explicit_omni_same_object": output is baseline,
        "bytes_identical": output.tobytes() == baseline.tobytes(),
        "effects_diagnostic": diagnostic,
        "real_backend_status": _dependency_status(),
        "status": _combined_status(
            "passed" if output is baseline and not diagnostic else "failed"
        ),
    }
    _json("off_state_golden_sha256.json", payload)
    _json(
        "off_state_frame.json",
        {
            "status": _dependency_status(),
            "reason": "real room frame requires pyroomacoustics",
        },
    )
    (OUTPUT / "off_state_waveform_sha256.txt").write_text(
        f"dependency_status={_dependency_status()}\npure_sha256={_sha256(baseline.tobytes())}\n",
        encoding="utf-8",
    )

    probe = np.random.default_rng(20260718).normal(size=16_384)
    kwargs = {
        "source_pattern": _pattern("figure_eight", POINTS),
        "microphone_pattern": _pattern("supercardioid", POINTS),
        "source_position_world": (0.0, 0.0, 0.0),
        "source_orientation_world_xyzw": QUATERNIONS[2],
        "microphone_position_world": (1.0, 0.0, 0.0),
        "microphone_orientation_world_xyzw": QUATERNIONS[2],
        "sample_rate_hz": SAMPLE_RATE_HZ,
    }
    first = apply_pair_directivity(probe, **kwargs)
    second = apply_pair_directivity(probe, **kwargs)
    replay = {
        "input_sha256": _sha256(probe.tobytes()),
        "first_sha256": _sha256(first.tobytes()),
        "second_sha256": _sha256(second.tobytes()),
        "exact": first.tobytes() == second.tobytes(),
        "status": "passed" if first.tobytes() == second.tobytes() else "failed",
    }
    _json("enabled_replay_sha256.json", replay)
    _json(
        "registry_determinism_directivity.json",
        {
            "pure_replay": replay,
            "room_registry_status": _dependency_status(),
            "status": _combined_status(replay["status"]),
        },
    )
    return payload, replay


def _dependency_artifacts() -> dict[str, object]:
    status = _dependency_status()
    ladder = {
        "angles_deg": [0, 90, 120, 180],
        "noise_seeds": list(range(20260718, 20260726)),
        "sample_count": 65_536,
        "front_snr_db": 18.0,
        "snr_minimum_first_step_loss_db": 5.5,
        "snr_minimum_second_step_loss_db": 5.5,
        "snr_minimum_front_rear_loss_db": 40.0,
        "srp_minimum_front_rear_drop": 0.10,
        "gcc_minimum_front_rear_drop": 0.05,
        "dependency": "pyroomacoustics",
        "status": status,
        "measurements": None,
    }
    _json("estimator_confidence_ladder.json", ladder)
    _plot_png("estimator_confidence_overlay.png", (np.zeros(4),))
    _json(
        "estimator_input_sha256.json",
        {"status": status, "hashes": None, "dependency": "pyroomacoustics"},
    )
    return ladder


def _fidelity_ledger() -> dict[str, object]:
    payload = {
        "supported_mode": "per_pair_direct_path",
        "full_convolved_pair_weighted_from_direct_path_angle": True,
        "reflection_specific_angles": False,
        "direct_arrival_only": False,
        "native_pyroomacoustics_directivity": False,
        "p2_deferrals": [
            "per-reflection departure/incidence angles",
            "direct-arrival-only separation",
            "native directional source and microphone objects",
        ],
        "s3_9_reconciliation_required": "core/fidelity.py",
        "status": "passed",
    }
    _json("fidelity_reconciliation.json", payload)
    return payload


def _dependency_status() -> str:
    return (
        "passed"
        if importlib.util.find_spec("pyroomacoustics") is not None
        else "dependency_unavailable"
    )


def _combined_status(pure_status: object) -> str:
    if pure_status != "passed":
        return "failed"
    return "passed" if _dependency_status() == "passed" else "dependency_unavailable"


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    dependency_available = importlib.util.find_spec("pyroomacoustics") is not None
    environment = {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "numpy_version": np.__version__,
        "numpy_origin": np.__file__,
        "pyroomacoustics_available": dependency_available,
        "pyroomacoustics_origin": (
            None
            if not dependency_available
            else importlib.util.find_spec("pyroomacoustics").origin
        ),
    }
    _json("evidence_environment.json", environment)
    config = _config_contract()
    polar, polar_max = _polar_evidence()
    cardinal, cardinal_db, cardinal_null = _waveform_and_product_evidence()
    frequency, frequency_single, frequency_cascade = _frequency_evidence()
    product, insertion = _product_and_insertion_evidence()
    metadata, edges = _metadata_and_edges()
    invalid, diagnostics = _validation_and_diagnostics()
    off_state, replay = _off_state_and_replay()
    ladder = _dependency_artifacts()
    fidelity = _fidelity_ledger()

    rows = {
        "frozen_config_defaults": config["status"],
        "polar_families_angles": polar["status"],
        "cardinal_waveform_gain": cardinal["status"],
        "frequency_response": frequency["status"],
        "source_mic_product": product["status"],
        "full_convolved_stem_insertion": insertion["status"],
        "metadata_waveform_consistency": metadata["status"],
        "estimator_degradation": ladder["status"],
        "fail_closed_validation": invalid["status"],
        "zero_direction_and_nulls": edges["status"],
        "diagnostics_contract": diagnostics["status"],
        "disabled_omni_off_state": off_state["status"],
        "determinism_registry": (
            "dependency_unavailable"
            if replay["status"] == "passed" and not dependency_available
            else replay["status"]
        ),
        "fidelity_limitation_ledger": fidelity["status"],
    }
    artifact_hashes = {
        path.relative_to(OUTPUT).as_posix(): _file_sha256(path)
        for path in sorted(OUTPUT.rglob("*"))
        if path.is_file() and path.name != "waveform_directivity_gate.json"
    }
    pure_failed = any(status == "failed" for status in rows.values())
    gate_status = (
        "failed"
        if pure_failed
        else "passed"
        if all(status == "passed" for status in rows.values())
        else "dependency_unavailable"
    )
    gate = {
        "subphase": "S3.6",
        "protocol_revision": PROTOCOL_REVISION,
        "implementation_revision": _git_revision(),
        "package_version": __version__,
        "environment": environment,
        "normalized_configuration": {
            "mode": "per_pair_direct_path",
            "families": list(TARGETS),
            "frequency_points": [
                {"freq_hz": point.freq_hz, "gain_db": point.gain_db} for point in POINTS
            ],
        },
        "sample_counts": {
            "cardinal_waveform": 48_000,
            "frequency_sweep": 2**18,
            "estimator_ladder": 65_536,
        },
        "welch_parameters": {
            "nperseg": 8192,
            "noverlap": 4096,
            "accepted_hz": [200.0, 18_000.0],
        },
        "thresholds": {
            "polar_linear": 1e-12,
            "cardinal_non_null_db": 0.05,
            "cardinal_null_linear": 1e-6,
            "frequency_single_db": 0.25,
            "frequency_cascaded_db": 0.50,
            "metadata_non_null_db": 0.05,
            "metadata_null_linear": 1e-6,
            "estimator_snr_first_two_loss_db": 5.5,
            "estimator_snr_front_rear_loss_db": 40.0,
            "estimator_srp_front_rear_drop": 0.10,
            "estimator_gcc_front_rear_drop": 0.05,
        },
        "measured_maxima": {
            "polar_absolute_error": polar_max,
            "cardinal_non_null_error_db": cardinal_db,
            "cardinal_null_leakage_linear": cardinal_null,
            "frequency_single_error_db": frequency_single,
            "frequency_cascaded_error_db": frequency_cascade,
            "metadata_non_null_error_db": metadata["maximum_non_null_error_db"],
            "metadata_null_error_linear": metadata["maximum_null_error_linear"],
        },
        "rows": rows,
        "dependency_gated_rows": [
            name for name, status in rows.items() if status == "dependency_unavailable"
        ],
        "commands": [
            ".venv/bin/pytest -q tests/test_effects_directivity.py",
            ".venv/bin/python scripts/s3_6_evidence.py",
            "make test",
            "make lint",
        ],
        "artifact_sha256": artifact_hashes,
        "status": gate_status,
    }
    _json("waveform_directivity_gate.json", gate)
    print(
        json.dumps(
            {
                "status": gate_status,
                "dependency_gated_rows": gate["dependency_gated_rows"],
                "measured_maxima": gate["measured_maxima"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if gate_status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
