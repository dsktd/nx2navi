"""Blender (headless) scene for a modelx .glb: studio lights, camera, one CPU render.

blender -b --python tools/modelx-blend.py -- <model.glb> <out.blend> <preview.png>
"""

import math
import sys

import bpy
from mathutils import Vector


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_model(path):
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    root = next(o for o in bpy.context.scene.objects if o.parent is None)
    root.rotation_mode = "XYZ"
    root.rotation_euler = (-math.pi / 2, 0.0, 0.0)  # blade (game +Z) points up
    bpy.context.view_layer.update()
    return meshes


def bounds(objects):
    corners = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    lo = Vector(min(c[i] for c in corners) for i in range(3))
    hi = Vector(max(c[i] for c in corners) for i in range(3))
    return lo, hi


def add_light(name, kind, energy, location, size=1.0):
    data = bpy.data.lights.new(name, kind)
    data.energy = energy
    if kind == "AREA":
        data.size = size
    light = bpy.data.objects.new(name, data)
    light.location = location
    bpy.context.collection.objects.link(light)
    aim(light, Vector((0.0, 0.0, 0.0)))
    return light


def aim(obj, target):
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def studio(lo, hi):
    centre, size = (lo + hi) / 2, max(hi - lo)
    for o in bpy.context.scene.objects:
        if o.parent is None and o.type != "LIGHT":
            o.location -= centre
    add_light("Key", "AREA", 300.0, Vector((1.2, -1.6, 1.0)) * size, size)
    add_light("Fill", "AREA", 80.0, Vector((-1.6, -1.0, 0.3)) * size, size)
    add_light("Rim", "AREA", 250.0, Vector((0.0, 1.8, 0.8)) * size, size * 0.5)
    world = bpy.data.worlds.new("Studio")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.05, 0.06, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
    bpy.context.scene.world = world
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    cam.data.lens = 85.0
    cam.location = Vector((0.9, -2.6, 0.25)) * size
    bpy.context.collection.objects.link(cam)
    aim(cam, Vector((0.0, 0.0, 0.0)))
    bpy.context.scene.camera = cam


def render(path):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 96
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 900, 1200
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def main():
    model, blend, preview = sys.argv[sys.argv.index("--") + 1 :]
    reset()
    meshes = import_model(model)
    studio(*bounds(meshes))
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    render(preview)


main()
