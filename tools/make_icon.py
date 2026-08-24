"""Build the app icon from the logo artwork.

A .ico holds several sizes, and they do not have to be the same drawing. The
logo has "VR GALLERY" set into it, which is unreadable mush at 16 px and turns
the whole tile to noise, so the small entries get the mark only -- the camera on
the logo's gradient, in a rounded square -- while the large ones keep the full
logo. That is what an icon this shape needs to stay recognisable in the tray.

    .venv\\Scripts\\python.exe tools\\make_icon.py [source.png]
"""
import io
import os
import struct
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = os.path.join(os.path.expanduser("~"), "Desktop", "VRGallery.png")
OUT_ICO = os.path.join(HERE, "assets", "VRGallery.ico")
OUT_PNG = os.path.join(HERE, "assets", "VRGallery.png")

# measured from the artwork rather than eyeballed
CAMERA_BOX = (640, 225, 1560, 975)      # the camera with room for its outline
TEAL = (13, 202, 176)
BLUE = (30, 172, 237)
INK = (17, 17, 17)

FULL_AT = (256, 128)                    # sizes that keep the wordmark
MARK_AT = (64, 48, 32, 24, 16)          # below 128 the words are mush


def _trimmed(src):
    box = src.getchannel("A").getbbox()
    return src.crop(box) if box else src


def full_tile(src, size):
    """The whole logo, fitted into a square with a little air around it."""
    art = _trimmed(src)
    inner = int(size * 0.94)
    art = art.copy()
    art.thumbnail((inner, inner), Image.LANCZOS)
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile.paste(art, ((size - art.width) // 2, (size - art.height) // 2), art)
    return tile


def _gradient(size):
    """The logo's teal->blue run, on the same diagonal."""
    g = Image.new("RGBA", (size, size))
    px = g.load()
    span = max(1, (size - 1) * 2)
    for y in range(size):
        for x in range(size):
            t = (x + y) / span
            px[x, y] = (round(TEAL[0] + (BLUE[0] - TEAL[0]) * t),
                        round(TEAL[1] + (BLUE[1] - TEAL[1]) * t),
                        round(TEAL[2] + (BLUE[2] - TEAL[2]) * t), 255)
    return g


def mark_tile(src, size):
    """Camera on the gradient, in a rounded square with the logo's black edge."""
    ss = 8 if size <= 64 else 2                  # supersample; small sizes need it
    big = size * ss
    stroke = max(2, int(round(big * 0.055)))
    radius = int(big * 0.235)

    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius, fill=255)

    tile = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    tile.paste(_gradient(big), (0, 0), mask)
    ImageDraw.Draw(tile).rounded_rectangle(
        (stroke // 2, stroke // 2, big - 1 - stroke // 2, big - 1 - stroke // 2),
        radius, outline=INK + (255,), width=stroke)

    cam = _trimmed(src.crop(CAMERA_BOX))
    want = int(big * 0.62)
    cam = cam.copy()
    cam.thumbnail((want, want), Image.LANCZOS)
    tile.paste(cam, ((big - cam.width) // 2, (big - cam.height) // 2), cam)
    return tile.resize((size, size), Image.LANCZOS)


def write_ico(path, tiles):
    """ICO with a PNG payload per entry, so each size keeps its own drawing.

    Pillow's own ICO writer takes one image and rescales it, which is exactly
    what we are avoiding here.
    """
    blobs = []
    for tile in tiles:
        buf = io.BytesIO()
        tile.save(buf, format="PNG")
        blobs.append(buf.getvalue())
    header = struct.pack("<HHH", 0, 1, len(tiles))
    offset = len(header) + 16 * len(tiles)
    entries, body = b"", b""
    for tile, blob in zip(tiles, blobs):
        w = 0 if tile.width >= 256 else tile.width
        h = 0 if tile.height >= 256 else tile.height
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        body += blob
    with open(path, "wb") as f:
        f.write(header + entries + body)


def main(argv):
    src_path = argv[1] if len(argv) > 1 else DEFAULT_SRC
    if not os.path.exists(src_path):
        print(f"no artwork at {src_path}")
        return 1
    src = Image.open(src_path).convert("RGBA")
    os.makedirs(os.path.dirname(OUT_ICO), exist_ok=True)

    tiles = [full_tile(src, s) for s in FULL_AT] + [mark_tile(src, s) for s in MARK_AT]
    write_ico(OUT_ICO, tiles)
    full_tile(src, 512).save(OUT_PNG)             # for the About box and the README
    mark_tile(src, 256).save(os.path.join(HERE, "assets", "VRGallery-mark.png"))

    got = Image.open(OUT_ICO)
    print(f"{OUT_ICO}  {os.path.getsize(OUT_ICO):,} bytes")
    print("  sizes:", sorted(got.info.get("sizes", []), reverse=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
