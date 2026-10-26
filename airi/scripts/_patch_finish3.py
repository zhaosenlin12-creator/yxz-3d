from pathlib import Path
p = Path("scripts/finish_yxz_mouth.py")
t = p.read_text(encoding="utf-8")
t = t.replace("LINING_CLEARANCE = 0.0030", """# How far behind the plate the lining sits.  It is almost nothing in the
# middle, so that the closed mouth is a line rather than a hole, and it
# grows towards the rim, so that an open mouth has somewhere to go.
LINING_CLEARANCE = 0.0005
LINING_RISE = 0.0025""")
t = t.replace("""        z, _ = plate_z(x, y, None)
        rings.append(np.column_stack([x, y, z - LINING_CLEARANCE]))""",
"""        z, _ = plate_z(x, y, None)
        clearance = LINING_CLEARANCE + LINING_RISE * radius ** 2
        rings.append(np.column_stack([x, y, z - clearance]))""")
t = t.replace("""    floor = np.array([[centre[0], centre[1],
                       rings[-1][:, 2].mean() - 0.0015]])""",
"""    floor = np.array([[centre[0], centre[1],
                       rings[-1][:, 2].mean() - 0.0008]])""")
p.write_text(t, encoding="utf-8")
print("patched")
