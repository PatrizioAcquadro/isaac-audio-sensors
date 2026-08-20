from __future__ import annotations

import pytest

from tools.release.audit_distribution import audit_distribution
from tools.release.content_policy import ContentPolicyError


def test_distribution_audit_accepts_wheel_and_sdist(
    tmp_path, wheel_bytes, write_zip, write_tar
):
    write_zip(tmp_path / "package.whl", {"package/__init__.py": ""})
    write_tar(
        tmp_path / "package.tar.gz",
        {"package/pyproject.toml": "[build-system]\n"},
    )

    assert len(audit_distribution(tmp_path)) == 2


def test_distribution_audit_requires_both_formats(tmp_path, write_zip):
    write_zip(tmp_path / "package.whl", {"package/__init__.py": ""})

    with pytest.raises(ContentPolicyError, match="wheel and source"):
        audit_distribution(tmp_path)


def test_distribution_audit_rejects_nested_test_code(
    tmp_path, wheel_bytes, write_zip, write_tar
):
    write_zip(tmp_path / "package.whl", {"te" + "sts/leak.py": ""})
    write_tar(tmp_path / "package.tar.gz", {"package/pyproject.toml": ""})

    with pytest.raises(ContentPolicyError):
        audit_distribution(tmp_path)
