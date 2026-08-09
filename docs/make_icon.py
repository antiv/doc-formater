#!/usr/bin/env python3
"""Generate the application icon.

The icon is drawn as SVG here rather than committed as an opaque binary so that
a colour or proportion can be changed by editing one number. The PNG exports are
produced by rendering that same SVG in Chromium, which keeps every size pixel
identical to the master.

    python docs/make_icon.py

Requires playwright (``pip install playwright && playwright install chromium``),
which is deliberately not in requirements.txt — it is only needed to regenerate
assets, never to run the app.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

INK = "#1E2532"  # tamna pozadina, dovoljno neutralna i za svetlu i za tamnu temu
PAPER = "#FFFFFF"
MUTED = "#C3CBD9"  # neformatirani redovi
CORAL = "#FF4B4B"  # vođica margine; ista boja kao Streamlit akcenat

# Priča ikone: gornji redovi su razbacani, donji su poravnati na koralnu
# vođicu margine. Tekst je isti — promenio se samo raspored, što je tačno ono
# što aplikacija radi sa dokumentom.
RAGGED = [(168, 176, 108), (210, 190, 152), (252, 172, 124)]  # y, x, širina
ALIGNED = [(300, 200), (338, 200), (376, 200), (414, 128)]  # y, širina


def build_svg() -> str:
    rows = [f'<rect x="112" y="80" width="288" height="368" rx="24" fill="{PAPER}"/>']
    rows += [
        f'<rect x="{x}" y="{y}" width="{w}" height="16" rx="8" fill="{MUTED}"/>'
        for y, x, w in RAGGED
    ]
    rows += [
        f'<rect x="160" y="{y}" width="{w}" height="16" rx="8" fill="{INK}"/>'
        for y, w in ALIGNED
    ]
    rows.append(f'<rect x="136" y="160" width="10" height="270" rx="5" fill="{CORAL}"/>')
    body = "\n  ".join(rows)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" '
        'width="512" height="512" role="img" aria-label="Doc Formatter">\n'
        f'  <rect width="512" height="512" rx="112" fill="{INK}"/>\n'
        f"  {body}\n"
        "</svg>\n"
    )


# Zaobljeni uglovi moraju biti providni, pa se render radi nad providnom
# stranicom (`omit_background`), a ne nad belom.
_PAGE = """<!doctype html><meta charset="utf-8"><style>
  html,body {{ margin:0; padding:0; background:transparent; }}
  svg {{ display:block; width:{size}px; height:{size}px; }}
</style>{svg}"""

SIZES = {"icon-512.png": 512, "icon-192.png": 192, "favicon-32.png": 32}


def main() -> int:
    from playwright.sync_api import sync_playwright

    ASSETS.mkdir(exist_ok=True)
    svg = build_svg()
    (ASSETS / "icon.svg").write_text(svg, encoding="utf-8")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for filename, size in SIZES.items():
            page = browser.new_page(
                viewport={"width": size, "height": size}, device_scale_factor=1
            )
            page.set_content(_PAGE.format(size=size, svg=svg))
            page.wait_for_timeout(120)
            page.screenshot(path=str(ASSETS / filename), omit_background=True)
            page.close()
            print(f"  {filename}  {size}x{size}")
        browser.close()

    print(f"  icon.svg\nWritten to {ASSETS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
