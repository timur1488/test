"""Original pixel textures, generated locally without downloading assets."""

import random
from PIL import Image, ImageDraw

TILE = 16
ATLAS_COLUMNS = 16  # Power-of-two dimensions also support Panda3D's software renderer.
PALETTE = {
    "grass": (100, 160, 63), "dirt": (128, 86, 55),
    "stone": (133, 143, 151), "sand": (226, 211, 152),
    "wood": (136, 99, 55), "leaves": (66, 128, 57), "brick": (176, 91, 66),
}
TILES = ("grass", "grass_side", "dirt", "stone", "sand", "wood", "wood_top",
         "leaves", "brick")


def create_atlas():
    atlas = Image.new("RGB", (ATLAS_COLUMNS * TILE, TILE))
    rng = random.Random(123)
    for index, name in enumerate(TILES):
        tile = Image.new("RGB", (TILE, TILE))
        for y in range(TILE):
            for x in range(TILE):
                base = PALETTE.get(name, PALETTE["dirt"])
                if name == "grass_side":
                    base = PALETTE["grass"] if y < 3 + (x * 7 % 3) else PALETTE["dirt"]
                if name in ("wood", "wood_top"):
                    base = PALETTE["wood"]
                noise = rng.randint(-18, 18)
                if name == "wood":
                    noise += -22 if x % 4 == 0 else 6
                if name == "wood_top":
                    ring = int(max(abs(x - 7.5), abs(y - 7.5)))
                    noise += -25 if ring % 3 == 0 else 18
                tile.putpixel((x, y), tuple(max(0, min(255, c + noise)) for c in base))
        if name == "brick":
            draw = ImageDraw.Draw(tile)
            for y in (0, 8):
                draw.line((0, y, 15, y), fill=(199, 184, 157), width=1)
                x = 0 if y == 0 else 8
                draw.line((x, y, x, y + 7), fill=(199, 184, 157), width=1)
        atlas.paste(tile, (index * TILE, 0))
    return atlas


def face_uv(kind, normal):
    tile = kind
    if kind == "grass":
        tile = "grass" if normal[1] > 0 else "dirt" if normal[1] < 0 else "grass_side"
    elif kind == "wood" and normal[1]:
        tile = "wood_top"
    index = TILES.index(tile)
    # Sample inside the tile to avoid bleeding into adjacent textures.
    left, right = (index + .03) / ATLAS_COLUMNS, (index + .97) / ATLAS_COLUMNS
    return ((left, .03), (right, .03), (right, .97), (left, .97))
