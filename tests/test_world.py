import json
import math
from pathlib import Path
import tempfile
import unittest

from world import BLOCKS, CHUNK_SIZE, FACES, World


class WorldTests(unittest.TestCase):
    def setUp(self):
        self.world = World(seed=42, size=16)

    def player(self):
        return {"position": list(self.world.spawn()), "yaw": 30, "pitch": 12, "selected": 2}

    def test_generation_is_repeatable_and_seed_changes_terrain(self):
        self.assertEqual(self.world.blocks, World(seed=42, size=16).blocks)
        self.assertNotEqual(self.world.blocks, World(seed=43, size=16).blocks)
        self.assertTrue(set(self.world.blocks.values()) <= set(BLOCKS))
        self.assertFalse(any(self.world.overlaps_player(pos, self.world.spawn())
                             for pos in self.world.blocks))

    def test_default_world_has_trees_and_safe_spawn(self):
        world = World()
        self.assertIn("wood", world.blocks.values())
        self.assertIn("leaves", world.blocks.values())
        self.assertEqual(world.safe_player_position(world.spawn()), world.spawn())

    def test_bedrock_and_world_limits(self):
        for pos in ((0, 0, 0), (-1, 10, 4), (16, 10, 4), (4, 64, 4)):
            self.assertFalse(self.world.set_block(pos, None))
            self.assertFalse(self.world.set_block(pos, "brick"))
        self.assertEqual(self.world.blocks[0, 0, 0], "stone")

    def test_edit_rebuilds_both_sides_of_chunk_boundary(self):
        dirty = self.world.set_block((CHUNK_SIZE - 1, 20, 5), "brick")
        self.assertEqual(dirty, {(0, 0), (1, 0)})
        self.assertFalse(self.world.set_block((CHUNK_SIZE - 1, 20, 5), "brick"))
        self.assertEqual(self.world.set_block((CHUNK_SIZE - 1, 20, 5), None), dirty)

    def test_mesh_hides_shared_faces_even_across_chunks(self):
        for pos in ((7, 20, 5), (8, 20, 5)):
            self.world.set_block(pos, "brick")
        faces = [face for chunk in ((0, 0), (1, 0))
                 for face in self.world.visible_faces(chunk) if face[0][1] == 20]
        self.assertEqual(len(faces), 10)
        self.world.set_block((8, 20, 5), None)
        faces = [face for face in self.world.visible_faces((0, 0)) if face[0][1] == 20]
        self.assertEqual(len(faces), 6)

    def test_faces_are_wound_outward(self):
        for normal, vertices, _ in FACES:
            a = [vertices[1][i] - vertices[0][i] for i in range(3)]
            b = [vertices[2][i] - vertices[0][i] for i in range(3)]
            cross = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
            self.assertEqual(cross, normal)

    def test_raycast_detects_nearest_block_and_correct_face(self):
        self.world.set_block((4, 20, 4), "brick")
        self.world.set_block((6, 20, 4), "stone")
        hit = self.world.raycast((1.5, 20.5, 4.5), (1, 0, 0))
        self.assertEqual(hit.position, (4, 20, 4))
        self.assertEqual(hit.normal, (-1, 0, 0))
        self.assertAlmostEqual(hit.distance, 2.5)
        self.assertIsNone(self.world.raycast((1.5, 20.5, 4.5), (1, 0, 0), reach=2))
        reverse = self.world.raycast((5.5, 20.5, 4.5), (-1, 0, 0))
        self.assertEqual(reverse.normal, (1, 0, 0))
        self.assertIsNone(self.world.raycast((1, 20, 1), (0, 0, 0)))

    def test_raycast_handles_diagonals_and_origin_outside_world(self):
        self.world.set_block((0, 20, 4), "brick")
        hit = self.world.raycast((-2.5, 20.5, 4.5), (4, 0, 0))
        self.assertEqual(hit.position, (0, 20, 4))
        self.assertAlmostEqual(hit.distance, 2.5)
        self.world.set_block((5, 21, 5), "brick")
        hit = self.world.raycast((2.5, 21.5, 2.5), (1, 0, 1))
        self.assertEqual(hit.position, (5, 21, 5))
        self.assertAlmostEqual(hit.distance, 2.5 * math.sqrt(2))

    def test_placement_player_collision_includes_head_and_edges(self):
        player = (4.5, 10, 4.5)
        self.assertTrue(self.world.overlaps_player((4, 11, 4), player))
        self.assertTrue(self.world.overlaps_player((5, 10, 4), (4.9, 10, 4.5)))
        self.assertFalse(self.world.overlaps_player((4, 9, 4), player))
        self.assertFalse(self.world.overlaps_player((6, 10, 4), player))

    def test_save_roundtrip_and_atomic_replacement(self):
        self.world.set_block((4, 20, 4), "brick")
        self.world.set_block((4, 2, 4), None)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested/world.json"
            self.world.save(path, self.player())
            self.world.save(path, self.player())
            restored, player = World.load(path)
            self.assertEqual(restored.blocks, self.world.blocks)
            self.assertEqual(restored.edits, self.world.edits)
            self.assertEqual(player["selected"], 2)
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_invalid_saves_are_rejected_without_being_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "world.json"
            self.world.save(path, self.player())
            baseline = json.loads(path.read_text())
            for edits in ([[4, 0, 4, None]], [[4, 20, 4, "unknown"]],
                          [[-1, 20, 4, "brick"]], [[True, 20, 4, "brick"]]):
                data = {**baseline, "edits": edits}
                raw = json.dumps(data)
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    World.load(path)
                self.assertEqual(path.read_text(), raw)
            baseline["player"]["position"] = [float("nan"), 2, 3]
            path.write_text(json.dumps(baseline))
            with self.assertRaises(ValueError):
                World.load(path)

    def test_player_inside_block_or_outside_world_returns_to_spawn(self):
        self.assertEqual(self.world.safe_player_position((4.5, 2, 4.5)), self.world.spawn())
        self.assertEqual(self.world.safe_player_position((-10, 12, 4)), self.world.spawn())


if __name__ == "__main__":
    unittest.main()
