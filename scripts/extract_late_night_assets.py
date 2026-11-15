#!/usr/bin/env python3
"""Extract Late Night logos and Shake Smart dish image from R&DE banner."""

from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BANNER_PATH = ROOT / "data" / "shake_smart_banner.jpg"


def main():
    if not BANNER_PATH.exists():
        raise SystemExit(f"Banner not found: {BANNER_PATH}")

    img = Image.open(BANNER_PATH)

    # 1. Arrillaga Nights logo
    arrillaga_box = (537, 64, 761, 168)
    arrillaga_crop = img.crop(arrillaga_box)
    out_arrillaga = ROOT / "data" / "logos" / "arrillaga_late_night.webp"
    arrillaga_crop.save(out_arrillaga, "WEBP", quality=95)
    print(f"Saved {out_arrillaga} ({arrillaga_crop.size})")

    # 2. Lakeside Late Night Kitchen logo
    lakeside_box = (555, 244, 746, 327)
    lakeside_crop = img.crop(lakeside_box)
    out_lakeside = ROOT / "data" / "logos" / "lakeside_late_night.webp"
    lakeside_crop.save(out_lakeside, "WEBP", quality=95)
    print(f"Saved {out_lakeside} ({lakeside_crop.size})")

    # 3. Shake Smart Shakes dish image (1024x576 16:9 on white canvas)
    left_crop = img.crop((0, 0, 520, 605))
    target_w, target_h = 1024, 576
    dish_img = Image.new("RGB", (target_w, target_h), (255, 255, 255))
    scale = 550 / left_crop.height
    new_w = int(left_crop.width * scale)
    new_h = int(left_crop.height * scale)
    scaled = left_crop.resize((new_w, new_h), Image.Resampling.LANCZOS)
    x_offset = (target_w - new_w) // 2
    y_offset = (target_h - new_h) // 2
    dish_img.paste(scaled, (x_offset, y_offset))
    out_dish = ROOT / "data" / "images" / "bcda517df9b6.webp"
    dish_img.save(out_dish, "WEBP", quality=92)
    print(f"Saved {out_dish} ({dish_img.size})")


if __name__ == "__main__":
    main()
