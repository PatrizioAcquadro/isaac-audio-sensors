from __future__ import annotations

import hashlib
from pathlib import Path

from isaac_audio_sensors.acquisition.s4_7_prerequisite_corrective_03 import (
    CANONICAL_PREREQUISITE,
    REQUIRED_PACKAGE_FILES,
    validate_s4_7_corrective_03_prerequisite,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "outputs/isaac_audio_sensors/S4/S4.7_corrective_03"
SEAL = (
    ROOT
    / "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
    "s4_4_data_expansion_amendment_03/holdout_seal.v1.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_canonical_corrective_03_package_authenticates_exactly() -> None:
    authenticated = validate_s4_7_corrective_03_prerequisite(
        ROOT / CANONICAL_PREREQUISITE,
        seal_path=SEAL,
        require_committed=False,
        verify_replay=True,
    )
    assert authenticated["status"] == "passed"
    assert authenticated["package_file_count"] == 18
    assert authenticated["scientific_semantics_sha256"] == (
        "91c12a090102c7b1de6c250f5edd654620d845c5f1044c8ca466961f8756539d"
    )


def test_canonical_package_has_exact_files_and_principal_hashes() -> None:
    assert {path.name for path in PACKAGE.iterdir()} == REQUIRED_PACKAGE_FILES
    assert _sha256(PACKAGE / "SHA256SUMS") == (
        "6cfbb31bd4d96fb1138aa7ecb09156b550eadeed247fafb24d4e555d6361112f"
    )
    assert _sha256(PACKAGE / "holdout_acceptance.json") == (
        "9f266432f2045e858b8f52ba6dd1f69f401bfd445df73e4ab25775ad59ecefd9"
    )
    assert _sha256(PACKAGE / "criteria_register.json") == (
        "64e9fc170e81174f975d5d67b7ce94b765f967b3826e5e7cd61746ab59e25375"
    )


def test_every_package_checksum_is_valid() -> None:
    for line in (PACKAGE / "SHA256SUMS").read_text(
        encoding="utf-8"
    ).splitlines():
        digest, name = line.split("  ", 1)
        assert _sha256(PACKAGE / name) == digest
