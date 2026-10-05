"""Production purity verification.

Ensures zero-leak isolation: web/ source files and production build artifacts
must contain zero overlay identifiers, endpoints, or CSS classes.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_TERMS = [
    "bsdm-redraw",
    "bsdm-redraw-overlay",
    "btn-redraw-toggle",
    "card-redraw-active",
    "/api/redraw-queue",
    "redraw_queue",
]


def test_web_source_purity():
    """Verify that web/ source files have zero overlay references."""
    web_dir = ROOT / "web"
    for file in web_dir.iterdir():
        if file.suffix in (".html", ".js", ".css"):
            text = file.read_text(encoding="utf-8")
            for term in FORBIDDEN_TERMS:
                assert term not in text, f"Leak detected in {file.name}: found {term!r}"


def test_site_build_purity():
    """Verify that built site/ artifacts contain 0 bytes of overlay code."""
    site_index = ROOT / "site" / "index.html"
    if site_index.exists():
        text = site_index.read_text(encoding="utf-8")
        for term in FORBIDDEN_TERMS:
            assert term not in text, f"Leak detected in site/index.html: found {term!r}"


def test_compiled_site_purity(project, tmp_path):
    """Verify that freshly compiled site HTML contains 0 overlay terms."""
    from bsdm import build as buildlib
    from conftest import dish

    project.set_today("2026-09-17")
    project.add_hall("wilbur")
    project.write_catalog({})
    project.write_menu(
        "2026-09-17",
        {"wilbur": {"Dinner": [dish("Roast Chicken", "chicken")]}},
    )
    project.with_web()

    buildlib.build(project.root, tmp_path / "site")
    html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")

    for term in FORBIDDEN_TERMS:
        assert term not in html, f"Leak detected in compiled build: found {term!r}"


def test_bsdm_build_source_purity():
    """Verify that bsdm/build.py does not contain any overlay references."""
    build_py = ROOT / "bsdm" / "build.py"
    text = build_py.read_text(encoding="utf-8")
    for term in FORBIDDEN_TERMS:
        assert term not in text, f"Leak detected in bsdm/build.py: found {term!r}"


def test_redraw_queue_gitignored():
    """Verify that data/redraw_queue.json is ignored by git."""
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "redraw_queue.json" in gitignore
