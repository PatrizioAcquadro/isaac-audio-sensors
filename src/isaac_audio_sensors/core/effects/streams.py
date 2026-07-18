"""Frozen named-stream seed derivation for later stochastic effect stages."""

from __future__ import annotations

import hashlib

import numpy as np

SEED_DERIVATION_ID = "sha256-colon-v1-pcg64-le64"


def named_stream_key(
    seed: int,
    *,
    domain: str,
    frame_id: str,
    mic_id: str,
    effect: str,
) -> str:
    """Return the exact canonical UTF-8 stream-key text."""

    return f"{seed}:{domain}:{frame_id}:{mic_id}:{effect}"


def named_stream_descriptor(
    seed: int,
    *,
    domain: str,
    frame_id: str,
    mic_id: str,
    effect: str,
) -> tuple[str, str, int]:
    """Return canonical key, SHA-256 hex digest, and little-endian seed."""

    key = named_stream_key(
        seed,
        domain=domain,
        frame_id=frame_id,
        mic_id=mic_id,
        effect=effect,
    )
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return key, digest.hex(), int.from_bytes(digest[:8], "little", signed=False)


def named_generator(
    seed: int,
    *,
    domain: str,
    frame_id: str,
    mic_id: str,
    effect: str,
) -> np.random.Generator:
    """Construct the PCG64 generator specified by the frozen stream contract."""

    _key, _digest, derived = named_stream_descriptor(
        seed,
        domain=domain,
        frame_id=frame_id,
        mic_id=mic_id,
        effect=effect,
    )
    return np.random.Generator(np.random.PCG64(derived))


__all__ = [
    "SEED_DERIVATION_ID",
    "named_generator",
    "named_stream_descriptor",
    "named_stream_key",
]
