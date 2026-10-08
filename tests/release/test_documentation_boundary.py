from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WIKI_ROOT = REPO_ROOT / "knowledge" / "wiki"
WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


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


def test_maintained_markdown_links_resolve() -> None:
    pages = [REPO_ROOT / "README.md", REPO_ROOT / "CHANGELOG.md"]
    for root in (WIKI_ROOT, REPO_ROOT / "exts", REPO_ROOT / "examples"):
        pages.extend(root.rglob("*.md"))
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK_RE.findall(text):
            path = target.split("#", 1)[0]
            if not path or path.startswith(("http://", "https://", "mailto:")):
                continue
            target_path = (page.parent / path).resolve()
            assert target_path.exists(), f"{page}: unresolved Markdown link {target!r}"
