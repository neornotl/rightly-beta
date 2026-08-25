"""Generate the Windows icon used by both Rightly executables."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "rightly.ico"


def font(size: int):
    candidates = (
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    )
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def make(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (22, 49, 73, 255))
    draw = ImageDraw.Draw(image)
    scale = size / 256
    radius = int(48 * scale)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=(22, 49, 73, 255))
    mint = (130, 201, 163, 255)
    dark_mint = (92, 169, 138, 255)
    # Chat bubble outline and tail.
    draw.line([(62 * scale, 58 * scale), (153 * scale, 58 * scale)], fill=mint, width=max(3, int(16 * scale)))
    draw.line([(62 * scale, 58 * scale), (62 * scale, 157 * scale), (85 * scale, 157 * scale)], fill=mint, width=max(3, int(16 * scale)))
    draw.line([(62 * scale, 157 * scale), (62 * scale, 203 * scale), (107 * scale, 164 * scale)], fill=mint, width=max(3, int(16 * scale)))
    draw.arc((137 * scale, 58 * scale, 204 * scale, 125 * scale), 270, 90, fill=mint, width=max(3, int(16 * scale)))
    # Check mark.
    draw.line([(96 * scale, 137 * scale), (123 * scale, 164 * scale), (195 * scale, 88 * scale)], fill=mint, width=max(4, int(18 * scale)), joint="curve")
    draw.polygon([(135 * scale, 101 * scale), (166 * scale, 69 * scale), (198 * scale, 69 * scale), (151 * scale, 115 * scale)], fill=dark_mint)
    label = "Rightly"
    box = draw.textbbox((0, 0), label, font=font(max(10, int(28 * scale))))
    draw.text(((size - (box[2] - box[0])) / 2, 218 * scale), label, fill=mint, font=font(max(10, int(28 * scale))))
    return image


OUT.parent.mkdir(parents=True, exist_ok=True)
make(256).save(OUT, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print(OUT)
