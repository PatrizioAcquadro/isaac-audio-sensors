from __future__ import annotations

import hashlib
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[2]
WIKI_ROOT = REPO_ROOT / "knowledge" / "wiki"
R0_SHA256 = "d87efa29c8efc94bbcc05c732e65e560e810a7ff8fcaca8e0cc2cd3ac9adc748"
WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def test_root_docs_are_removed_and_authorized_r0_spec_is_preserved() -> None:
    assert not (REPO_ROOT / "docs").exists()
    r0_spec = (
        REPO_ROOT
        / "knowledge"
        / "raw"
        / "docs"
        / "00_repository_restructuring.md"
    )
    assert r0_spec.is_file()
    assert hashlib.sha256(r0_spec.read_bytes()).hexdigest() == R0_SHA256
    assert not (r0_spec.parent / ".gitkeep").exists()


def test_wiki_index_lists_every_canonical_page() -> None:
    index = (WIKI_ROOT / "index.md").read_text(encoding="utf-8")
    pages = {
        path.relative_to(WIKI_ROOT).with_suffix("").as_posix()
        for path in WIKI_ROOT.rglob("*.md")
        if path.name not in {"index.md", "log.md"}
    }
    for page in sorted(pages):
        assert f"[[{page}" in index, f"wiki page missing from index: {page}"


def test_every_internal_wikilink_resolves() -> None:
    for page in WIKI_ROOT.rglob("*.md"):
        text = page.read_text(encoding="utf-8")
        for match in WIKILINK_RE.finditer(text):
            target = match.group(1).split("|", 1)[0].split("#", 1)[0]
            target_path = WIKI_ROOT / f"{target}.md"
            assert target_path.is_file(), f"{page}: unresolved wikilink {target!r}"


def test_active_markdown_links_resolve_and_avoid_removed_root_docs() -> None:
    excluded_roots = {".git", "build", "dist", "evidence"}
    for page in REPO_ROOT.rglob("*.md"):
        relative = page.relative_to(REPO_ROOT)
        if relative.parts[0] in excluded_roots or relative.parts[:2] == (
            "knowledge",
            "raw",
        ):
            continue
        text = page.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK_RE.findall(text):
            path = target.split("#", 1)[0]
            assert not path.startswith("docs/"), (
                f"{page}: stale root-doc link {target!r}"
            )
            if not path or path.startswith(("http://", "https://", "mailto:")):
                continue
            target_path = (page.parent / path).resolve()
            assert target_path.exists(), f"{page}: unresolved Markdown link {target!r}"


def test_kit_metadata_is_standalone_and_wiki_is_not_a_packaged_doc_set() -> None:
    extension_root = REPO_ROOT / "exts" / "isaac_audio_sensors.omni"
    manifest_path = extension_root / "config" / "extension.toml"
    with manifest_path.open("rb") as stream:
        manifest = tomllib.load(stream)
    package = manifest["package"]
    assert (extension_root / package["readme"]).is_file()
    assert (extension_root / package["changelog"]).is_file()
    assert "documentation" not in manifest


def test_pyproject_has_no_obsolete_docs_extra() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as stream:
        pyproject = tomllib.load(stream)
    extras = pyproject["project"].get("optional-dependencies", {})
    assert "docs" not in extras
