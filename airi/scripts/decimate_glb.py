import sys
from pathlib import Path

import pymeshlab


def value_after(name: str) -> str:
    return sys.argv[sys.argv.index(name) + 1]


source = Path(value_after("--source"))
target = Path(value_after("--target"))
target.parent.mkdir(parents=True, exist_ok=True)
face_limit = int(value_after("--faces"))

mesh_set = pymeshlab.MeshSet()
mesh_set.load_new_mesh(str(source))
before = mesh_set.current_mesh().face_number()
mesh_set.apply_filter(
    "meshing_decimation_quadric_edge_collapse",
    targetfacenum=face_limit,
    preservenormal=True,
    preserveboundary=True,
    optimalplacement=True,
    autoclean=True,
)
after = mesh_set.current_mesh().face_number()
mesh_set.save_current_mesh(str(target), save_vertex_color=True, save_wedge_texcoord=True)
print(f"decimated {source} faces={before} -> {after} target={target}")
