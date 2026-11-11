"""Static guards: no hardcoded Chennai coordinates on any application path; logo asset is not distorted."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHENNAI = re.compile(r"13\.0827|80\.2707")
APP_DIRS = [ROOT / "backend" / d for d in ("api", "core", "workers")] + [ROOT / "backend" / "main.py", ROOT / "backend" / "config.py",
                                                                        ROOT / "frontend" / "src"]


def sources():
    for base in APP_DIRS:
        files = [base] if base.is_file() else [p for p in base.rglob("*") if p.suffix in (".py", ".js", ".jsx")]
        for p in files:
            if "__tests__" in p.parts:
                continue
            yield p


def test_no_chennai_coordinates_in_application_code():
    hits = [f"{p.relative_to(ROOT)}:{i + 1}" for p in sources() for i, line in enumerate(p.read_text(errors="ignore").splitlines())
            if CHENNAI.search(line)]
    assert hits == []


def test_map_viewport_is_the_only_chennai_reference_and_is_never_read_back():
    store = (ROOT / "frontend/src/components/Map/mapStore.js").read_text()
    assert ".setView([13.08, 80.27], 8)" in store                       # initial viewport only (allowed)
    for p in (ROOT / "frontend/src").rglob("*.js*"):
        text = p.read_text(errors="ignore")
        assert "getCenter(" not in text, p                              # simulation inputs never come from the viewport
        assert "getBounds().get" not in text or "fit" in text.lower()


def test_logo_asset_keeps_the_original_aspect_ratio():
    from PIL import Image
    branding = ROOT / "frontend/public/assets/branding"
    original = Image.open(branding / "sft-logo-original.jpg")
    web = Image.open(branding / "sft-logo.jpg")
    assert original.size == (8000, 3593)
    assert abs(web.size[0] / web.size[1] - original.size[0] / original.size[1]) < 0.002     # proportional resize only
    for n in (32, 64, 192):
        assert Image.open(branding / f"favicon-{n}.png").size == (n, n)


def test_logo_css_never_stretches():
    css = (ROOT / "frontend/src/styles/theme.css").read_text()
    assert ".logo-badge img { display: block; width: auto; height: 100%; max-width: 100%; object-fit: contain; }" in css
