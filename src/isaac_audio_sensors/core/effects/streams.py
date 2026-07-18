"""Frozen named-stream seed derivation for later stochastic effect stages."""

from __future__ import annotations

import hashlib

import numpy as np

SEED_DERIVATION_ID = "sha256-colon-v1-pcg64-le64"


def named_generator(
    seed: int,
    *,
    domain: str,
    frame_id: str,
    mic_id: str,
    effect: str,
) -> np.random.Generator:
    """Construct the PCG64 generator specified by the frozen stream contract."""

    key = f"{int(seed)}:{domain}:{frame_id}:{mic_id}:{effect}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    derived = int.from_bytes(digest[:8], "little", signed=False)
    return np.random.Generator(np.random.PCG64(derived))


__all__ = ["SEED_DERIVATION_ID", "named_generator"]
