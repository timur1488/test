"""Deterministic voxel world, independent of the graphics engine."""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import random

BLOCKS = ("grass", "dirt", "stone", "sand", "wood", "leaves", "brick")
CHUNK_SIZE = 8
MAX_HEIGHT = 64
DEFAULT_SIZE = 48
Position = tuple[int, int, int]

# Vertices are counterclockwise as seen from outside each face.
FACES = (
    ((0, 1, 0), ((0, 1, 1), (1, 1, 1), (1, 1, 0), (0, 1, 0)), 1.0),
    ((0, -1, 0), ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)), .48),
    ((1, 0, 0), ((1, 0, 1), (1, 0, 0), (1, 1, 0), (1, 1, 1)), .82),
    ((-1, 0, 0), ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)), .68),
    ((0, 0, 1), ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)), .9),
    ((0, 0, -1), ((1, 0, 0), (0, 0, 0), (0, 1, 0), (1, 1, 0)), .74),
)


@dataclass(frozen=True)
class Hit:
    position: Position
    normal: Position
    distance: float


class World:
    def __init__(self, seed=42, size=DEFAULT_SIZE):
        if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
            raise ValueError("Seed must be an integer from 0 to 4294967295")
        if type(size) is not int or not 16 <= size <= 96:
            raise ValueError("World size must be an integer from 16 to 96")
        self.seed, self.size = seed, size
        self.blocks: dict[Position, str] = {}
        self.edits: dict[Position, str | None] = {}
        self.chunks: dict[tuple[int, int], set[Position]] = {}
        self._generate()

    def _put(self, pos, kind):
        chunk = (pos[0] // CHUNK_SIZE, pos[2] // CHUNK_SIZE)
        if kind is None:
            self.blocks.pop(pos, None)
            self.chunks.setdefault(chunk, set()).discard(pos)
        else:
            self.blocks[pos] = kind
            self.chunks.setdefault(chunk, set()).add(pos)

    def _generate(self):
        rng = random.Random(self.seed)
        phase = rng.uniform(0, math.tau)
        heights = {}
        center = self.size // 2
        for x in range(self.size):
            for z in range(self.size):
                height = round(5 + 1.6 * math.sin(x / 7 + phase)
                               + 1.3 * math.cos(z / 9 - phase)
                               + .7 * math.sin((x + z) / 5))
                if abs(x - center) <= 3 and abs(z - center) <= 3:
                    height = 6
                heights[x, z] = height
                shore = min(x, z, self.size - 1 - x, self.size - 1 - z) < 3
                for y in range(height + 1):
                    kind = "stone" if y < height - 2 else "dirt"
                    if y == height:
                        kind = "sand" if shore else "grass"
                    self._put((x, y, z), kind)

        trees = []
        for x in range(4, self.size - 4):
            for z in range(4, self.size - 4):
                if abs(x - center) <= 5 and abs(z - center) <= 5:
                    continue
                if rng.random() > .023:
                    continue
                if any(abs(x - tx) < 4 and abs(z - tz) < 4 for tx, tz in trees):
                    continue
                trees.append((x, z))
                base = heights[x, z] + 1
                trunk = rng.randint(3, 4)
                for y in range(base, base + trunk):
                    self._put((x, y, z), "wood")
                for dy in range(-1, 2):
                    radius = 1 if dy == 1 else 2
                    for dx in range(-radius, radius + 1):
                        for dz in range(-radius, radius + 1):
                            if abs(dx) == radius and abs(dz) == radius:
                                continue
                            pos = (x + dx, base + trunk + dy, z + dz)
                            if pos not in self.blocks:
                                self._put(pos, "leaves")

    def in_bounds(self, pos):
        x, y, z = pos
        return 0 <= x < self.size and 0 <= z < self.size and 0 <= y < MAX_HEIGHT

    def set_block(self, pos: Position, kind: str | None):
        """Return affected chunks; the bottom layer cannot be edited."""
        if not self.in_bounds(pos) or pos[1] == 0:
            return set()
        if kind is not None and kind not in BLOCKS:
            raise ValueError("Unknown block type")
        if self.blocks.get(pos) == kind:
            return set()
        self._put(pos, kind)
        self.edits[pos] = kind
        x, _, z = pos
        # Include neighboring chunks when an exposed boundary face changes.
        affected = {(x // CHUNK_SIZE, z // CHUNK_SIZE)}
        for dx, dz in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            if 0 <= x + dx < self.size and 0 <= z + dz < self.size:
                affected.add(((x + dx) // CHUNK_SIZE, (z + dz) // CHUNK_SIZE))
        return affected

    def visible_faces(self, chunk):
        for pos in sorted(self.chunks.get(chunk, ())):
            kind = self.blocks[pos]
            for normal, vertices, shade in FACES:
                neighbor = tuple(pos[i] + normal[i] for i in range(3))
                if neighbor not in self.blocks:
                    yield pos, kind, normal, vertices, shade

    def spawn(self):
        center = self.size // 2
        top = max(y for x, y, z in self.blocks if x == center and z == center)
        return center + .5, top + 1.05, center + .5

    def raycast(self, origin, direction, reach=6.0):
        """Exact voxel traversal; works across chunk edges and in negative space."""
        magnitude = math.sqrt(sum(d * d for d in direction))
        if magnitude == 0:
            return None
        direction = tuple(d / magnitude for d in direction)
        cell = [math.floor(v) for v in origin]
        steps = [1 if d > 0 else -1 for d in direction]
        deltas = [abs(1 / d) if d else math.inf for d in direction]
        distances = [((cell[i] + (1 if direction[i] > 0 else 0) - origin[i])
                      / direction[i]) if direction[i] else math.inf for i in range(3)]
        distance, normal = 0.0, (0, 0, 0)
        while distance <= reach:
            if tuple(cell) in self.blocks:
                return Hit(tuple(cell), normal, distance)
            axis = min(range(3), key=distances.__getitem__)
            distance = distances[axis]
            cell[axis] += steps[axis]
            distances[axis] += deltas[axis]
            normal = tuple(-steps[axis] if i == axis else 0 for i in range(3))
        return None

    @staticmethod
    def overlaps_player(pos, player, height=1.8, radius=.32):
        return (pos[0] < player[0] + radius and pos[0] + 1 > player[0] - radius
                and pos[1] < player[1] + height and pos[1] + 1 > player[1]
                and pos[2] < player[2] + radius and pos[2] + 1 > player[2] - radius)

    def safe_player_position(self, position):
        if not (0 < position[0] < self.size and 0 < position[2] < self.size
                and 0 < position[1] < MAX_HEIGHT + 3):
            return self.spawn()
        x, y, z = position
        for bx in range(math.floor(x - .32), math.floor(x + .32) + 1):
            for by in range(math.floor(y), math.floor(y + 1.8) + 1):
                for bz in range(math.floor(z - .32), math.floor(z + .32) + 1):
                    pos = (bx, by, bz)
                    if pos in self.blocks and self.overlaps_player(pos, position):
                        return self.spawn()
        return tuple(position)

    def save(self, path, player):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "seed": self.seed, "size": self.size, "player": player,
                "edits": [[*pos, kind] for pos, kind in sorted(self.edits.items())]}
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False),
                             encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def load(cls, path):
        """Validate before applying any saved changes. Never overwrite bad saves."""
        path = Path(path)
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Save file is too large")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Unsupported save format")
        world = cls(seed=data.get("seed"), size=data.get("size"))
        edits = data.get("edits")
        if not isinstance(edits, list) or len(edits) > world.size**2 * MAX_HEIGHT:
            raise ValueError("Invalid block edits")
        for entry in edits:
            if not isinstance(entry, list) or len(entry) != 4:
                raise ValueError("Invalid block edit")
            x, y, z, kind = entry
            pos = (x, y, z)
            if (any(type(v) is not int for v in pos) or not world.in_bounds(pos)
                    or y == 0 or (kind is not None and kind not in BLOCKS)):
                raise ValueError("Invalid block edit")
            world.set_block(pos, kind)
        player = data.get("player")
        if not isinstance(player, dict):
            raise ValueError("Invalid player data")
        position = player.get("position")
        if (not isinstance(position, list) or len(position) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in position)):
            raise ValueError("Invalid player position")
        for key in ("yaw", "pitch"):
            value = player.get(key)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Invalid camera rotation")
        selected = player.get("selected")
        if type(selected) is not int or not 0 <= selected < len(BLOCKS):
            raise ValueError("Invalid selected block")
        player["position"] = world.safe_player_position(position)
        player["yaw"] %= 360
        player["pitch"] = max(-89, min(89, player["pitch"]))
        return world, player
