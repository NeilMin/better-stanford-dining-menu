from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_overlay_files_exist():
    css_file = ROOT / "scripts" / "overlay" / "overlay.css"
    js_file = ROOT / "scripts" / "overlay" / "overlay.js"

    assert css_file.exists(), "overlay.css must exist"
    assert js_file.exists(), "overlay.js must exist"

    css_text = css_file.read_text(encoding="utf-8")
    js_text = js_file.read_text(encoding="utf-8")

    assert ".btn-redraw-toggle" in css_text
    assert ".card-redraw-active" in css_text
    assert "bsdm-redraw-dock" in css_text

    assert "fetch('/api/redraw-queue'" in js_text
    assert "stopPropagation" in js_text
    assert "dataset.state" in js_text


@pytest.mark.node
def test_overlay_js_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    js_file = ROOT / "scripts" / "overlay" / "overlay.js"
    assert js_file.exists(), "overlay.js must exist for syntax check"
    res = subprocess.run([node, "--check", str(js_file)], capture_output=True, text=True)
    assert res.returncode == 0, f"JS syntax error: {res.stderr}"
