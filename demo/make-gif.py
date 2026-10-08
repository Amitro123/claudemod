"""Stitches demo/frames/*.png (from render-frames.mjs) into ../assets/pixel-buddy.gif."""

from pathlib import Path

from PIL import Image

here = Path(__file__).parent
frames = sorted((here / "frames").glob("*.png"))
if not frames:
    raise SystemExit("no frames: run `node render-frames.mjs` first")

images = [Image.open(f).convert("RGB") for f in frames]
# One shared palette keeps the colors steady from frame to frame and the file small.
palette = images[len(images) // 2].quantize(colors=255, method=Image.Quantize.MEDIANCUT)
quantized = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in images]

out = here.parent / "assets" / "pixel-buddy.gif"
out.parent.mkdir(exist_ok=True)
quantized[0].save(out, save_all=True, append_images=quantized[1:], duration=150, loop=0, optimize=True, disposal=1)
print(f"{out} — {len(frames)} frames, {out.stat().st_size / 1024:.0f} KB")
