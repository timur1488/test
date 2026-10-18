"""MiniCraft: a small creative voxel sandbox written in Python."""

import argparse
from pathlib import Path
import sys
import tempfile

from world import BLOCKS, MAX_HEIGHT, World


def parse_args():
    parser = argparse.ArgumentParser(description="MiniCraft — a Python voxel sandbox")
    parser.add_argument("--seed", type=int, default=42, help="Seed for a new world")
    parser.add_argument("--save", type=Path, default=Path(__file__).parent / "saves/world.json")
    parser.add_argument("--smoke-test", action="store_true", help="Test offscreen rendering and gameplay")
    parser.add_argument("--screenshot", type=Path, help="Screenshot path for the smoke test")
    return parser.parse_args()


def run(args):
    if not (3, 12) <= sys.version_info[:2] < (3, 15):
        raise ValueError(
            "Use Python 3.12 (supported: 3.12-3.14). Panda3D has no Windows "
            "wheel for Python 3.15. In the game folder, run:\n"
            "uv run --python 3.12 --with-requirements requirements.txt main.py"
        )
    # Configure before initializing the engine. The headless renderer is only
    # used by the automated offscreen check, never forced during normal play.
    from panda3d.core import loadPrcFileData
    loadPrcFileData("", "audio-library-name null\nnotify-level warning")
    if args.smoke_test:
        loadPrcFileData("", "load-display p3headlessgl\naux-display p3tinydisplay\nwindow-type offscreen")

    from ursina import (Ursina, Entity, Mesh, Texture, Text, Button, Vec3, camera,
                        color, mouse, scene, window, application, held_keys, time,
                        destroy, raycast)
    from ursina.prefabs.first_person_controller import FirstPersonController
    from textures import PALETTE, TILE, TILES, create_atlas, face_uv

    if args.save.exists() and not args.smoke_test:
        try:
            world, saved_player = World.load(args.save)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"Cannot load {args.save}: {exc}. "
                             "Use --save with another path to create a new world.") from exc
    else:
        world, saved_player = World(args.seed), None

    app = Ursina(title="MiniCraft · Python", size=(1280, 720), fullscreen=False,
                 borderless=False, development_mode=False, editor_ui_enabled=False,
                 window_type="offscreen" if args.smoke_test else "onscreen")
    if args.smoke_test:
        # Ursina's mouse setter assumes an OS window. A render buffer has no
        # pointer to capture; retain its logical state without requesting one.
        class OffscreenMouse(type(mouse)):
            @property
            def locked(self):
                return self._locked

            @locked.setter
            def locked(self, value):
                self._locked = value

        mouse.__class__ = OffscreenMouse
    # Offscreen buffers do not emit Ursina's usual aspect-ratio window event.
    camera.ui_lens.set_film_size(camera._ui_size * .5 * window.aspect_ratio,
                                 camera._ui_size * .5)
    window.color = color.rgb32(151, 198, 226)
    window.exit_button.enabled = False
    scene.fog_color = window.color
    scene.fog_density = (32, 85)
    atlas_image = create_atlas()
    atlas = Texture(atlas_image, filtering=None)
    terrain = Entity(name="terrain")
    chunks = {}

    def rebuild(chunk):
        vertices, triangles, uvs, colors, normals = [], [], [], [], []
        for pos, kind, normal, corners, shade in world.visible_faces(chunk):
            offset = len(vertices)
            vertices.extend(tuple(pos[i] + corner[i] for i in range(3)) for corner in corners)
            # Ursina uses y-up-left coordinates, so Panda's front faces need
            # the opposite winding from the right-handed face definitions.
            triangles.extend((offset, offset + 2, offset + 1, offset, offset + 3, offset + 2))
            uvs.extend(face_uv(kind, normal))
            colors.extend([(shade, shade, shade, 1)] * 4)
            normals.extend([normal] * 4)
        old = chunks.pop(chunk, None)
        if old:
            destroy(old)
        if vertices:
            mesh = Mesh(vertices=vertices, triangles=triangles, uvs=uvs,
                        colors=colors, normals=normals, static=True)
            chunks[chunk] = Entity(parent=terrain, name=f"chunk_{chunk}", model=mesh,
                                   texture=atlas, collider="mesh")

    for chunk in sorted(world.chunks):
        rebuild(chunk)

    player = FirstPersonController(position=world.spawn(), height=1.8, speed=5,
                                   jump_height=1.25, jump_up_duration=.3, fall_after=.22,
                                   traverse_target=terrain)
    player.cursor.enabled = False
    camera.fov = 85
    camera.clip_plane_far = 120
    if saved_player:
        player.position = saved_player["position"]
        player.rotation_y = saved_player["yaw"]
        player.camera_pivot.rotation_x = saved_player["pitch"]

    # Thin edges leave the target texture visible.
    outline = Entity(enabled=False)
    for axis in range(3):
        other = [i for i in range(3) if i != axis]
        for a in (-.505, .505):
            for b in (-.505, .505):
                position, scale = [0, 0, 0], [.012, .012, .012]
                position[other[0]], position[other[1]] = a, b
                scale[axis] = 1.022
                Entity(parent=outline, model="cube", position=position, scale=scale,
                       color=color.rgba32(30, 39, 44, 220))

    ui = Entity(parent=camera.ui)
    Entity(parent=ui, model="quad", scale=(.022, .003), color=color.white, z=-.1)
    Entity(parent=ui, model="quad", scale=(.003, .022), color=color.white, z=-.1)
    Text(parent=ui, text="MINICRAFT", position=(-.84, .46), scale=1.55,
         color=color.rgb32(255, 245, 217))
    Text(parent=ui, text="CREATIVE SANDBOX", position=(-.84, .413), scale=.72,
         color=color.rgb32(233, 241, 243))
    Text(parent=ui, text="WASD move  |  SPACE jump  |  SHIFT sprint\n"
                        "LMB break  |  RMB place  |  MMB pick\n"
                        "1-7 / wheel select  |  F5 save  |  ESC pause",
         position=(-.84, -.34), scale=.76, line_height=1.3)
    coords = Text(parent=ui, position=(.84, .46), origin=(.5, .5), scale=.85)
    status = Text(parent=ui, y=.32, origin=(0, 0), scale=1.0,
                  color=color.rgb32(255, 244, 205))
    block_label = Text(parent=ui, y=-.315, origin=(0, 0), scale=.9)
    slots = []
    for index, kind in enumerate(BLOCKS):
        slot = Entity(parent=ui, model="quad", position=((index - 3) * .086, -.425),
                      scale=(.079, .079), color=color.rgba32(25, 36, 42, 205))
        tile_index = TILES.index(kind)
        icon = Texture(atlas_image.crop((tile_index * TILE, 0, (tile_index + 1) * TILE, TILE)))
        Entity(parent=slot, model="quad", texture=icon, scale=.62, z=-.01)
        Text(parent=slot, text=str(index + 1), position=(-.41, .44, -.02), scale=8)
        slots.append(slot)

    # Held block gives immediate feedback when switching inventory slots.
    hand = Entity(parent=camera, model="cube", position=(.57, -.43, 1),
                  scale=.28, rotation=(12, -25, 7), texture=atlas)
    pause_ui = Entity(parent=camera.ui, enabled=False, z=-2)
    Entity(parent=pause_ui, model="quad", scale=(3.6, 2), color=color.rgba32(15, 24, 31, 185))
    Text(parent=pause_ui, text="PAUSED", y=.23, origin=(0, 0), scale=2)
    Button(parent=pause_ui, text="Resume", y=.08, scale=(.34, .07),
           color=color.rgb32(70, 116, 85), on_click=lambda: game.set_paused(False))
    Button(parent=pause_ui, text="Save world", y=-.025, scale=(.34, .07),
           color=color.rgb32(66, 90, 108), on_click=lambda: game.save())
    Button(parent=pause_ui, text="Save and quit", y=-.13, scale=(.34, .07),
           color=color.rgb32(85, 72, 68), on_click=lambda: game.quit())
    pause_status = Text(parent=pause_ui, y=-.25, origin=(0, 0), scale=.9,
                        color=color.rgb32(255, 244, 205))

    class Game(Entity):
        def __init__(self):
            super().__init__()
            self.selected = saved_player["selected"] if saved_player else 0
            self.paused = False
            self.target = None
            self.message_time = 0
            self.save_time = 0
            self.select(self.selected)
            self.notify("Build anything. Your world saves automatically.", 5)

        def select(self, index):
            self.selected = index % len(BLOCKS)
            for i, slot in enumerate(slots):
                slot.color = (color.rgb32(226, 198, 128) if i == self.selected
                              else color.rgba32(25, 36, 42, 205))
            kind = BLOCKS[self.selected]
            hand.texture = Texture(atlas_image.crop((TILES.index(kind) * TILE, 0,
                                                     (TILES.index(kind) + 1) * TILE, TILE)))
            block_label.text = kind.upper()

        def notify(self, message, duration=2.5):
            status.text = message
            pause_status.text = message
            self.message_time = duration

        def save(self):
            if args.smoke_test:
                return True
            try:
                world.save(args.save, {"position": list(player.position),
                                      "yaw": player.rotation_y,
                                      "pitch": player.camera_pivot.rotation_x,
                                      "selected": self.selected})
            except (OSError, ValueError) as exc:
                self.notify("Save failed. Check the terminal.", 6)
                print(f"Save failed: {exc}", file=sys.stderr)
                return False
            self.notify("World saved")
            self.save_time = 0
            return True

        def quit(self):
            if self.save():
                application.quit()

        def set_paused(self, paused):
            self.paused = paused
            # Freeze jump animations too; UI input remains active while paused.
            application.time_scale = 0 if paused else 1
            player.enabled = not paused
            player.cursor.enabled = False
            mouse.locked = not paused
            pause_ui.enabled = paused
            ui.enabled = not paused
            hand.enabled = not paused
            outline.enabled = False
            if paused:
                self.save()

        def edit(self, position, kind):
            affected = world.set_block(position, kind)
            for chunk in sorted(affected):
                rebuild(chunk)
            return bool(affected)

        def input(self, key):
            if key == "escape":
                self.set_paused(not self.paused)
                return
            if key == "f5":
                self.save()
            if self.paused:
                return
            if key in "1234567" and len(key) == 1:
                self.select(int(key) - 1)
            if key in ("scroll up", "scroll down"):
                self.select(self.selected + (-1 if key == "scroll up" else 1))
            hit = world.raycast(tuple(camera.world_position), tuple(camera.forward))
            if not hit:
                return
            if key == "left mouse down":
                if not self.edit(hit.position, None):
                    self.notify("The bottom layer cannot be broken")
            elif key == "middle mouse down":
                self.select(BLOCKS.index(world.blocks[hit.position]))
            elif key == "right mouse down":
                position = tuple(hit.position[i] + hit.normal[i] for i in range(3))
                if position in world.blocks:
                    return
                if World.overlaps_player(position, tuple(player.position)):
                    self.notify("Step back to place this block")
                elif not world.in_bounds(position):
                    self.notify(f"World boundary: {world.size} x {world.size}, height {MAX_HEIGHT}")
                else:
                    self.edit(position, BLOCKS[self.selected])

        def update(self):
            if self.paused:
                return
            player.speed = 8 if (held_keys["left shift"] or held_keys["right shift"]) else 5
            self.message_time -= time.dt
            if self.message_time <= 0:
                status.text = ""
            self.save_time += time.dt
            if self.save_time >= 30:
                self.save_time = 0
                self.save()
            if player.y < -12:
                if hasattr(player, "y_animator"):
                    player.y_animator.pause()
                player.position = world.spawn()
                player.air_time = 0
                self.notify("Back at spawn")
            self.target = world.raycast(tuple(camera.world_position), tuple(camera.forward))
            outline.enabled = self.target is not None
            if self.target:
                outline.position = Vec3(*self.target.position) + Vec3(.5, .5, .5)
            coords.text = f"{player.x:.0f} / {player.y:.0f} / {player.z:.0f}"

    game = Game()
    # The window close button follows the same save path as the pause menu.
    app.userExit = game.quit

    if args.smoke_test:
        from panda3d.core import ClockObject
        clock = ClockObject.getGlobalClock()
        clock.setMode(ClockObject.MNonRealTime)
        clock.setDt(1 / 60)
        mouse.enabled = False
        mouse.locked = False
        # Check real mesh colliders, edit/rebuild them, and verify persistence.
        probe = (world.size // 2, 12, world.size // 2 + 4)
        assert game.edit(probe, "brick")
        hit = raycast(Vec3(probe[0] + .5, 16, probe[2] + .5), Vec3(0, -1, 0),
                      traverse_target=terrain, distance=8)
        assert hit.hit and abs(hit.world_point.y - 13) < .01, "Placed block collider missing"
        assert hit.world_normal.y > .9, "Top face points inward"
        player.position = (probe[0] + .5, probe[1] - player.height + .5, probe[2] - 3.5)
        player.rotation_y = 0
        player.camera_pivot.rotation_x = 0
        game.select(3)
        game.input("right mouse down")
        adjacent = (probe[0], probe[1], probe[2] - 1)
        assert world.blocks.get(adjacent) == "sand", "Place input failed"
        game.input("left mouse down")
        assert adjacent not in world.blocks, "Break input failed"
        game.input("middle mouse down")
        assert BLOCKS[game.selected] == "brick", "Pick input failed"
        assert game.edit(probe, None)
        hit = raycast(Vec3(probe[0] + .5, 16, probe[2] + .5), Vec3(0, -1, 0),
                      traverse_target=terrain, distance=16)
        assert hit.hit and hit.world_point.y < 12, "Removed block collider is still active"
        game.select(6)
        assert game.selected == 6
        game.set_paused(True)
        assert not player.enabled and not mouse.locked
        game.set_paused(False)
        assert player.enabled
        mouse.locked = False
        assert (camera.world_position - (player.world_position + Vec3(0, 1.8, 0))).length() < .01, \
            "Pause moved the camera away from the player"
        # Exercise the actual controller against the generated terrain.
        player.position = Vec3(*world.spawn()) + Vec3(0, 1, 0)
        player.air_time = 0
        for _ in range(90):
            app.taskMgr.step()
        assert player.grounded and abs(player.y - 7) < .1, "Player did not land on terrain"
        ground_y = player.y
        app.input("space")
        for _ in range(8):
            app.taskMgr.step()
        assert player.y > ground_y + .5, "Jump did not rise above the terrain"
        for _ in range(60):
            app.taskMgr.step()
        assert player.grounded and abs(player.y - ground_y) < .1, "Player did not land after jumping"
        old_position = Vec3(player.position)
        held_keys["w"] = 1
        held_keys["left shift"] = 1
        for _ in range(15):
            app.taskMgr.step()
        held_keys["w"] = 0
        held_keys["left shift"] = 0
        assert (player.position - old_position).length() > 1, "Movement is blocked"
        assert player.speed == 8, "Sprint did not activate"
        player.gravity = 0
        player.position = (world.size / 2 + .5, 11, world.size / 2 + .5)
        player.rotation_y = 28
        player.camera_pivot.rotation_x = 25
        with tempfile.TemporaryDirectory() as directory:
            save = Path(directory) / "world.json"
            world.save(save, {"position": list(player.position), "yaw": 28,
                              "pitch": 25, "selected": 6})
            restored, _ = World.load(save)
            assert restored.blocks == world.blocks
        for _ in range(8):
            app.taskMgr.step()
        app.graphicsEngine.renderFrame()
        if args.screenshot:
            from panda3d.core import Filename
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            assert app.win.saveScreenshot(Filename.fromOsSpecific(str(args.screenshot.resolve())))
        assert app.win and app.win.isValid(), "No render buffer"
        print(f"SMOKE TEST PASSED: {len(world.blocks)} blocks, {len(chunks)} chunks; "
              "rendering, colliders, build inputs, movement, jumping, sprint, inventory, pause and saves verified.")
        app.destroy()
    else:
        app.run()


if __name__ == "__main__":
    try:
        run(parse_args())
    except ModuleNotFoundError as exc:
        if exc.name.split(".")[0] not in {"panda3d", "ursina", "PIL", "direct"}:
            raise
        print(
            f"MiniCraft: missing dependency {exc.name!r} in {sys.executable}.\n"
            "In the game folder, install dependencies and run with Python 3.12:\n"
            "uv run --python 3.12 --with-requirements requirements.txt main.py\n"
            "Or install requirements.txt using the same Python that runs the game.",
            file=sys.stderr,
        )
        sys.exit(1)
    except (ValueError, OSError) as exc:
        print(f"MiniCraft: {exc}", file=sys.stderr)
        sys.exit(1)
