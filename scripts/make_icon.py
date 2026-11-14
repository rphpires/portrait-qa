"""Draw the application icon (portrait frame + check mark) into portrait_qa/assets/. Needs Pillow."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "portrait_qa" / "assets"


def draw(size: int = 256) -> Image.Image:
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8 * s, 8 * s, 248 * s, 248 * s], radius=44 * s, fill=(36, 84, 170, 255))
    # head and shoulders
    d.ellipse([88 * s, 52 * s, 168 * s, 142 * s], fill=(236, 241, 250, 255))
    d.pieslice([48 * s, 140 * s, 208 * s, 300 * s], 180, 360, fill=(236, 241, 250, 255))
    # framing corners
    w = max(2, round(10 * s))
    for x, y, dx, dy in ((36, 36, 1, 1), (220, 36, -1, 1), (36, 220, 1, -1), (220, 220, -1, -1)):
        d.line([(x * s, y * s), ((x + 34 * dx) * s, y * s)], fill=(255, 255, 255, 255), width=w)
        d.line([(x * s, y * s), (x * s, (y + 34 * dy) * s)], fill=(255, 255, 255, 255), width=w)
    # check badge
    d.ellipse([160 * s, 160 * s, 244 * s, 244 * s], fill=(39, 160, 92, 255), outline=(255, 255, 255, 255), width=w)
    d.line([(180 * s, 203 * s), (197 * s, 220 * s), (225 * s, 183 * s)], fill=(255, 255, 255, 255), width=round(12 * s))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw(256)
    big.save(OUT / "icon.png")
    big.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {OUT / 'icon.png'} and icon.ico")


if __name__ == "__main__":
    main()
