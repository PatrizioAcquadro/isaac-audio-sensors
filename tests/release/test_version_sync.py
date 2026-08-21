from __future__ import annotations

from pathlib import Path

import pytest

from tools.release.check_version_sync import _top_changelog_version


@pytest.mark.parametrize(
    "heading",
    (
        "## 2.0.0\n",
        "## 2.0.0 - Unreleased\n",
        "## 2.0.0 - 2026-08-21\n",
    ),
)
def test_top_changelog_version_accepts_release_states(tmp_path: Path, heading: str):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(f"# Changelog\n\n{heading}", encoding="utf-8")

    assert _top_changelog_version(changelog) == "2.0.0"


def test_top_changelog_version_rejects_invalid_date(tmp_path: Path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## 2.0.0 - 2026-02-30\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="day is out of range"):
        _top_changelog_version(changelog)
