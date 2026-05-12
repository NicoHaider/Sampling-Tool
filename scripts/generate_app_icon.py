"""Generiert App-Icons als Platzhalter (Mac .icns + Windows .ico + PNG-Quellen).

Erzeugt ein einfaches Icon mit BDO-Rot und "BDO" in Weiß. Sobald ein echtes
Icon vorhanden ist, kann dieses Script übersprungen werden und nur die
Output-Files (.icns, .ico) ausgetauscht werden.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "resources" / "icons"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BDO_RED = (232, 26, 59)
WHITE = (255, 255, 255)

SIZES = [16, 32, 48, 64, 128, 256, 512, 1024]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def render_png(size: int) -> Path:
    img = Image.new("RGBA", (size, size), BDO_RED)
    draw = ImageDraw.Draw(img)
    font = _load_font(max(8, size // 3))
    text = "BDO"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) / 2 - bbox[0]
    y = (size - text_h) / 2 - bbox[1]
    draw.text((x, y), text, fill=WHITE, font=font)
    png_path = OUT_DIR / f"icon_{size}.png"
    img.save(png_path)
    return png_path


def build_ico(png_paths: dict[int, Path]) -> Path:
    ico_path = OUT_DIR / "app.ico"
    wanted = [16, 32, 48, 64, 128, 256]
    images = [Image.open(png_paths[s]) for s in wanted if s in png_paths]
    images[0].save(
        ico_path,
        format="ICO",
        sizes=[(i.width, i.height) for i in images],
    )
    return ico_path


def build_icns(png_paths: dict[int, Path]) -> Path | None:
    iconset_dir = OUT_DIR / "app.iconset"
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir()

    iconset_layout: dict[int, list[str]] = {
        16: ["icon_16x16.png"],
        32: ["icon_16x16@2x.png", "icon_32x32.png"],
        64: ["icon_32x32@2x.png"],
        128: ["icon_128x128.png"],
        256: ["icon_128x128@2x.png", "icon_256x256.png"],
        512: ["icon_256x256@2x.png", "icon_512x512.png"],
        1024: ["icon_512x512@2x.png"],
    }
    for size, targets in iconset_layout.items():
        if size not in png_paths:
            continue
        for target in targets:
            shutil.copy(png_paths[size], iconset_dir / target)

    icns_path = OUT_DIR / "app.icns"
    if not shutil.which("iconutil"):
        print("iconutil nicht gefunden (nur auf macOS verfügbar). .icns wird nicht erzeugt.")
        print("PyInstaller fällt unter Linux/Windows auf icon_1024.png zurück.")
        return None

    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)],
        check=True,
    )
    shutil.rmtree(iconset_dir)
    return icns_path


def main() -> int:
    png_paths: dict[int, Path] = {}
    for size in SIZES:
        path = render_png(size)
        png_paths[size] = path
        print(f"Created {path}")

    ico_path = build_ico(png_paths)
    print(f"Created {ico_path}")

    icns_path = build_icns(png_paths)
    if icns_path is not None:
        print(f"Created {icns_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
