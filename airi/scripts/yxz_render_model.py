import bpy
import math
import sys
from pathlib import Path
from mathutils import Vector


def arg_after(name: str) -> str:
    args = sys.argv
    return args[args.index(name) + 1]


glb_path = Path(arg_after("--glb"))
output_path = Path(arg_after("--out"))
axis = arg_after("--axis") if "--axis" in sys.argv else "z+"
output_path.parent.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
if glb_path.suffix.lower() == ".obj":
    bpy.ops.wm.obj_import(filepath=str(glb_path))
else:
    bpy.ops.import_scene.gltf(filepath=str(glb_path))

meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
if not meshes:
    raise RuntimeError(f"No mesh found in {glb_path}")

for obj in bpy.context.scene.objects:
    obj.select_set(False)

min_corner = Vector((float("inf"), float("inf"), float("inf")))
max_corner = Vector((float("-inf"), float("-inf"), float("-inf")))
for obj in meshes:
    for corner in obj.bound_box:
        world_corner = obj.matrix_world @ Vector(corner)
        min_corner.x = min(min_corner.x, world_corner.x)
        min_corner.y = min(min_corner.y, world_corner.y)
        min_corner.z = min(min_corner.z, world_corner.z)
        max_corner.x = max(max_corner.x, world_corner.x)
        max_corner.y = max(max_corner.y, world_corner.y)
        max_corner.z = max(max_corner.z, world_corner.z)

center = (min_corner + max_corner) * 0.5
size = max(max_corner - min_corner)
for obj in meshes:
    obj.location -= center

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 720
scene.render.resolution_y = 720
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(output_path)
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("YXZWorld")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.025, 0.04, 0.08, 1.0)
scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.35

def add_area(name: str, location: tuple[float, float, float], energy: float, size_value: float, color: tuple[float, float, float]):
    bpy.ops.object.light_add(type="AREA", location=location)
    light = bpy.context.object
    light.name = name
    light.data.energy = energy
    light.data.shape = "DISK"
    light.data.size = size_value
    light.data.color = color
    direction = -Vector(location)
    light.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

camera_locations = {
    "x+": (size * 2.5, 0, size * 0.32),
    "x-": (-size * 2.5, 0, size * 0.32),
    "y+": (0, size * 2.5, size * 0.32),
    "y-": (0, -size * 2.5, size * 0.32),
    "z+": (0, 0, size * 2.5),
    "z-": (0, 0, -size * 2.5),
}
camera_location = camera_locations.get(axis, camera_locations["z+"])
add_area("Key", (camera_location[0] * 0.8 + size * 0.8, camera_location[1] * 0.8 + size * 0.8, size * 1.8), 1400, size * 1.2, (0.78, 0.9, 1.0))
add_area("Fill", (camera_location[0] * 0.5 - size * 0.8, camera_location[1] * 0.5 - size * 0.8, size * 0.6), 900, size * 1.4, (0.35, 0.65, 1.0))
add_area("Rim", (-camera_location[0] * 0.7, -camera_location[1] * 0.7, size * 1.4), 1200, size, (0.1, 0.75, 1.0))

bpy.ops.object.camera_add(location=camera_location)
camera = bpy.context.object
camera.data.lens = 55
camera.data.sensor_width = 36
camera.rotation_euler = (-camera.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = camera

scene.render.filepath = str(output_path)
bpy.ops.render.render(write_still=True)
print(f"rendered {output_path} bounds={tuple(min_corner)}..{tuple(max_corner)}")
