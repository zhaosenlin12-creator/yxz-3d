"""Turn the rigged YXZ GLB into a VRM 1.0 asset.

Blender has no VRM exporter, but the runtime already loads VRM through
`@pixiv/three-vrm`, so the extension is written straight into the GLB's JSON
chunk.  That keeps the skin, the Draco-free buffers and the morph targets
exactly as Blender wrote them.

  blender --background --python scripts/vrm_postprocess.py -- \
    --input <glb> --output <vrm> [--look-at <json>] [--title <name>]
    [--allow-missing-morphs]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from glb_json import (  # noqa: E402
    neutralise_weights,
    prune_buffers,
    read_glb,
    write_glb,
)


# three-vrm's humanoid map.  Anything not listed is simply absent from the
# VRM, which is legal; a name that is listed but missing from the model is a
# hard error, so the list has to match the rig exactly.
HUMANOID = {
    "hips": "hips",
    "spine": "spine",
    "chest": "chest",
    "upperChest": "upperChest",
    "neck": "neck",
    "head": "head",
    "leftEye": "leftEye",
    "rightEye": "rightEye",
    "jaw": "jaw",
    "leftShoulder": "leftShoulder",
    "leftUpperArm": "leftUpperArm",
    "leftLowerArm": "leftLowerArm",
    "leftHand": "leftHand",
    "rightShoulder": "rightShoulder",
    "rightUpperArm": "rightUpperArm",
    "rightLowerArm": "rightLowerArm",
    "rightHand": "rightHand",
    "leftUpperLeg": "leftUpperLeg",
    "leftLowerLeg": "leftLowerLeg",
    "leftFoot": "leftFoot",
    "leftToes": "leftToes",
    "rightUpperLeg": "rightUpperLeg",
    "rightLowerLeg": "rightLowerLeg",
    "rightFoot": "rightFoot",
    "rightToes": "rightToes",
}

# The rig has no jaw; a helmet character does not need one.
REQUIRED = [name for name in HUMANOID if name != "jaw"]

# VRM 1.0 preset expressions, mapped to the morph target each one drives.
EXPRESSIONS = {
    "happy": "happy",
    "angry": "angry",
    "sad": "sad",
    "relaxed": "relaxed",
    "surprised": "surprised",
    "aa": "aa",
    "ih": "ih",
    "ou": "ou",
    "ee": "ee",
    "blink": "blink",
    "blinkLeft": "blinkLeft",
    "blinkRight": "blinkRight",
}


# The Tripo asset ships as a scanned PBR mesh: one base-colour atlas, a
# metallic-roughness map and a normal map.  Rendered as a physical material it
# reads as glossy plastic, which is the single biggest reason the character
# does not feel like the AIRI avatar.  MToon is what that avatar is built
# with: a two-tone cel ramp with a soft rim and a silhouette outline, so the
# same texture reads as a stylised character instead of a shiny toy.
#
# The base-colour texture index is reused as the MToon texture, which is
# exactly the same image -- only the lighting model changes.
#
# The MToon colours are written in sRGB, which is what the specification
# asks for and what three-vrm assumes: it decodes them on load, so a value
# of 0.46 ends up as a linear 0.18.  An earlier revision of this script
# treated them as linear, and every colour came out roughly twice as light
# as it was written.
#
# The shade tone is what the shadowed half of the character is painted in,
# so it decides whether the model reads as a drawn character or as a white
# toy.  It is a cool grey-blue -- cool so the shadow reads as shadow and
# not as a dirty grey, and light enough that the character keeps its
# friendliness; a genuinely dark shade turns the whole figure into a
# silhouette.
MTOON_SHADE_COLOR = [0.40, 0.44, 0.60]
# The halo's own shade: the same hue as its light, a little deeper.  A
# ring whose shadow side is the body's grey-blue stops being a ring of
# light and becomes a piece of bent pipe.
HALO_SHADE_COLOR = [0.30, 0.62, 0.70]
# The rim is what separates a white character from a white page.  It is kept
# well below white on purpose: MToon adds it on top of the surface, so a
# near-white rim clips and paints flat white smears across the shell, and
# the smears are what made this character look broken up.
MTOON_RIM_COLOR = [0.52, 0.68, 0.95]

# No MToon outline is written on purpose.
#
# An MToon outline is a second pass that draws a material's *back* faces pushed
# out along the vertex normals, which only reads as a silhouette line when the
# mesh is a closed shell of even thickness.  The Tripo body is a merge of many
# sheets that carry real interior surfaces, and `probe_yxz_shell_geometry.py`
# measures 43% of the shell's triangles facing away from the camera.  Those
# interior sheets therefore leak ink straight across the character: rendering
# the outline pass on its own showed the helmet rim drawing a band over the
# chin and every panel seam drawing a line over the body, which together read
# as a grey veil.  That is the geometry, so no width factor tunes it away.
#
# The silhouette now comes from a depth/normal edge pass instead -- see the
# OutlinePass setup in `YXZRealModelScene.vue`, which only reacts where the
# depth buffer actually breaks and so ignores the interior sheets entirely.
#
# (Should this ever be revisited: VRM 1.0 spells `outlineWidthMode` as a string
# enum -- "none" | "worldCoordinates" | "screenCoordinates".  The integer
# 0/1/2 form is VRM 0.x legacy, and three-vrm passes the field through without
# coercing it while only generating the outline material for a string.)


def to_mtoon(material):
    """Turn one glTF material into an MToon material."""
    pbr = material.get("pbrMetallicRoughness", {})
    base_color = pbr.get("baseColorTexture", {}).get("index")
    # The halo is a ring of light, and the body's shade colour is a cool
    # grey-blue that is right for a white shell and wrong for a ring: a
    # grey shadow side turns the halo into a piece of bent pipe.  Its
    # shadow side keeps the halo's own hue instead, so the ring reads as
    # one lit object all the way round.
    halo = str(material.get("name", "")).startswith("YXZ_Halo")
    # MToon's `color` is the equivalent of glTF's `baseColorFactor`, and it is
    # the only place a flat tint can live now that the texture is optional.
    # Dropping it turns every deliberately dark part -- the eye socket, the
    # shadow disc behind the iris, the mouth cavity -- into a white surface
    # with only its outline left, which reads as goggles rather than eyes.
    base_color_factor = pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0])
    mtoon = {
        # three-vrm rejects an extension without a known specVersion and falls
        # back to a standard PBR material, which is exactly the glossy plastic
        # look this conversion exists to remove.
        "specVersion": "1.0",
        "color": base_color_factor,
        "shadeColorFactor": HALO_SHADE_COLOR if halo else MTOON_SHADE_COLOR,
        # In the MToon gradient `shadingToonyFactor` is the width of the ramp
        # between the lit tone and the shade tone:
        #
        #     linearstep(-1 + toony, 1 - toony, dotNL + shift)
        #
        # so a low value spreads the ramp over most of the surface, the lit
        # tone never reaches full white anywhere, and the character comes
        # out as a soft grey lump.  That is the plastic look, and no amount
        # of lighting fixes it.  A high value narrows the ramp to a couple
        # of degrees and the character reads as a cel: a lit shape, a shade
        # shape, and one clean line between them.
        #
        # The loader pulls the factor towards 1 before it reaches the shader
        # (`lerp(toony, 1, 0.5 + 0.5 * shift)`), so 0.9 is written here and
        # arrives as 0.95 -- a terminator a few degrees wide, which is what
        # the AIRI avatar uses.
        #
        # The field name matters: VRMC_materials_mtoon calls it
        # `shadingToonyFactor`, and three-vrm reads that exact key.  Writing
        # `shadeToonyFactor` instead -- which is what an earlier revision of
        # this script did -- makes the loader drop the value on the floor.
        "shadingToonyFactor": 0.92,
        "reflectanceFactor": 0.0,
        # `parametricRimColorFactor`, `parametricRimFresnelPowerFactor` and
        # `parametricRimLiftFactor` are the names VRMC_materials_mtoon uses.
        # They are the same in VRM 0.x and 1.0, and three-vrm reads them
        # verbatim, so spelling them `rimColorFactor` / `rimFresnelPower` /
        # `rimLiftFactor` leaves the character with no rim light at all.
        "parametricRimColorFactor": MTOON_RIM_COLOR,
        "rimLightingMixFactor": 0.5,
        # A high fresnel power keeps the rim on the true silhouette.  The
        # shader saturates it to 1 on any surface whose normal points away
        # from the camera, and a wide rim turns those surfaces into a flood
        # of light instead of an edge.
        "parametricRimFresnelPowerFactor": 2.3,
        "parametricRimLiftFactor": 0.04,
    }
    # The iris carries its own painted glints, but a touch of emission keeps
    # it reading as a lit lens instead of a flat sticker.
    emissive = material.get("emissiveFactor")
    if emissive:
        mtoon["emissiveFactor"] = emissive
    material["extensions"] = material.get("extensions", {})
    material["extensions"]["VRMC_materials_mtoon"] = mtoon
    # three-vrm's MToon plugin never reads the extension's own `texture`
    # field -- it takes `map` from the standard glTF baseColorTexture slot.
    # Dropping that slot silently leaves every material untextured, which
    # costs the iris its artwork and the shell its baked panel detail. The
    # normal and ORM maps really are unused by MToon, so those go instead.
    material.pop("normalTexture", None)
    material.pop("occlusionTexture", None)
    pbr.pop("metallicRoughnessTexture", None)
    material["pbrMetallicRoughness"] = {
        "baseColorFactor": base_color_factor,
        "metallicFactor": 0.0,
        "roughnessFactor": 1.0,
    }
    if base_color is not None:
        material["pbrMetallicRoughness"]["baseColorTexture"] = {"index": base_color}
    return material


def value_after(name, default=None):
    if name not in sys.argv:
        return default
    return sys.argv[sys.argv.index(name) + 1]


def index_nodes(document):
    return {node.get("name"): index for index, node in enumerate(document["nodes"])}


def find_node(nodes, bone_name):
    """The node index for a bone name.

    Blender writes the bone name straight onto the glTF node, but a rig that
    went through a rigify-style prefixing pass would carry
    `mixamorig:hips`.  An exact match wins; a suffix match is the fallback.
    """
    if bone_name in nodes:
        return nodes[bone_name]
    for name, index in nodes.items():
        if name and name.endswith(bone_name):
            return index
    return None


def morph_bindings(document):
    """Map every morph target name to the node and slot it lives in."""
    found = {}
    for mesh in document.get("meshes", []):
        if sum(len(p.get("targets", [])) for p in mesh.get("primitives", [])) > 0 \
                and len(mesh["primitives"]) > 1:
            # VRM addresses morph targets by a flat index over the mesh, which
            # is only unambiguous when a mesh has a single primitive.
            raise SystemExit("mesh " + str(mesh.get("name"))
                             + " splits its morph targets across primitives")
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            names = mesh.get("extras", {}).get("targetNames", [])
            for slot, target_name in enumerate(names):
                found.setdefault(target_name, []).append(
                    (mesh.get("name"), primitive_index, slot))
    return found


def build_vrm(document, nodes, bindings, look_offset, title,
              allow_missing_morphs=False):
    missing_bones = [name for name in REQUIRED
                     if not any(n.endswith(name) for n in nodes)]
    if missing_bones:
        raise SystemExit("rig is missing VRM bones: " + ", ".join(missing_bones))

    missing_morphs = sorted(name for name in EXPRESSIONS.values()
                            if name not in bindings)
    if missing_morphs and not allow_missing_morphs:
        raise SystemExit("model is missing morph targets: "
                         + ", ".join(missing_morphs))

    def binding(name):
        # A morph can live on more than one mesh.  The blink is the case
        # that matters: the eyes are built as a shadow, a light and a
        # core, on each side, and the blink has to close all four of the
        # pieces that make an eye, not just the first one it finds.
        # Binding only the first leaves the character winking with one
        # eye shut and the other wide open, and the other pieces of the
        # eye stay lit inside a closed lid.
        targets = []
        for mesh_name, primitive, slot in bindings.get(name, []):
            node = nodes[mesh_name]
            if not any(t["node"] == node and t["index"] == slot
                       for t in targets):
                targets.append({"node": node, "index": slot, "weight": 1.0})
        # VRM 1.0 addresses morph targets through `morphTargetBinds`, a list
        # of {node, index, weight} triples, where `index` is the morph slot.
        # The flat `morphTarget` field belongs to the VRM 0.x schema, and
        # three-vrm reads whichever schema the file actually declares --
        # writing the 0.x shape into a 1.0 extension produces an expression
        # that exists in the manager but drives no geometry at all.
        return {
            "morphTargetBinds": targets,
        }

    return {
        "specVersion": "1.0",
        "meta": {
            "title": title,
            "version": "1.0",
            "authors": ["AIRI / YXZ"],
            "licenseUrl": "https://vrm.dev/licenses/1.0/",
            "avatarPermission": "onlyAuthor",
            "allowExcessivelyViolentUsage": False,
            "allowExcessivelySexualUsage": False,
            "commercialUsage": False,
            "allowPoliticalOrReligiousUsage": False,
            "allowAntisocialOrHateUsage": False,
            "creditNotation": "required",
            "sourceUrl": "https://github.com/moeru-ai/airi",
            "modification": "modified",
        },
        "humanoid": {
            # VRM 1.0 keys `humanBones` by bone name; VRM 0.x used an array
            # of {bone, node} objects.  three-vrm iterates the 1.0 map with
            # `Object.entries`, so the 0.x array is read as the bones "0",
            # "1", "2"... and every required bone comes back missing.
            "humanBones": {
                slot: {"node": find_node(nodes, name)}
                for slot, name in HUMANOID.items()
                if find_node(nodes, name) is not None
            },
        },
        "firstPerson": {"meshAnnotations": []},
        "lookAt": {
            "type": "bone",
            "offsetFromHeadBone": look_offset,
            # The eyes alone carry the gaze here, so the ranges have to be
            # wide enough to reach the viewer and to absorb the head motion
            # in the clips without the eyes running out of travel and
            # freezing in a half-turned stare.
            # VRM 1.0 spells a range map as an object of
            # {inputMaxValue, outputScale}; the bare numbers are the VRM
            # 0.x shape.  three-vrm reads `inputMaxValue` and
            # `outputScale` off the object, so a bare number makes the
            # importer fall back to 90/10 and the eyes end up turning by
            # about a degree instead of following the gaze.
            # `inputMaxValue` is the head-to-target angle (degrees) that
            # saturates the map; `outputScale` is the eye travel (degrees)
            # reached at that angle.
            "rangeMapHorizontalOuter": {"inputMaxValue": 45.0, "outputScale": 22.0},
            "rangeMapHorizontalInner": {"inputMaxValue": 22.0, "outputScale": 12.0},
            "rangeMapVerticalDown": {"inputMaxValue": 20.0, "outputScale": 14.0},
            "rangeMapVerticalUp": {"inputMaxValue": 20.0, "outputScale": 12.0},
        },
        "expressions": {
            "preset": {
                "happy": binding("happy"),
                "angry": binding("angry"),
                "sad": binding("sad"),
                "relaxed": binding("relaxed"),
                "surprised": binding("surprised"),
                "aa": binding("aa"),
                "ih": binding("ih"),
                "ou": binding("ou"),
                "ee": binding("ee"),
                "blink": binding("blink"),
                "blinkLeft": binding("blinkLeft"),
                "blinkRight": binding("blinkRight"),
            },
            "custom": {},
        },
    }


def main() -> None:
    source = Path(value_after("--input"))
    target = Path(value_after("--output"))
    title = value_after("--title", "YXZ")
    look_path = value_after("--look-at") or str(source.with_suffix(".lookat.json"))
    look_offset = json.loads(Path(look_path).read_text(encoding="utf-8"))

    document, binary = read_glb(source)
    neutralise_weights(document)
    nodes = index_nodes(document)
    bindings = morph_bindings(document)
    vrm = build_vrm(
        document,
        nodes,
        bindings,
        look_offset["offsetFromHeadBone"],
        title,
        allow_missing_morphs="--allow-missing-morphs" in sys.argv,
    )

    document.setdefault("extensionsUsed", [])
    for name in ("VRMC_vrm", "VRMC_materials_mtoon"):
        if name not in document["extensionsUsed"]:
            document["extensionsUsed"].append(name)
    document["extensions"] = document.get("extensions", {})
    # The extension has to live under its own name.  three-vrm decides
    # between the VRM 0.x and the VRM 1.0 reader by looking for
    # `extensions.VRMC_vrm`; a VRM 1.0 body parked under `extensions.VRM` is
    # read as a 0.x asset, which silently drops the expression bindings and
    # the look-at head offset.
    document["extensions"].pop("VRM", None)
    document["extensions"]["VRMC_vrm"] = vrm
    for material in document.get("materials", []):
        to_mtoon(material)

    binary, dropped = prune_buffers(document, binary)

    target.parent.mkdir(parents=True, exist_ok=True)
    write_glb(target, document, binary)
    print("YXZ_VRM_WRITTEN " + str(target))
    print("YXZ_VRM_SUMMARY " + json.dumps({
        "bones": len(vrm["humanoid"]["humanBones"]),
        "expressions": sorted(k for k, v in
                              vrm["expressions"]["preset"].items() if v),
        "lookAt": vrm["lookAt"],
        "materials": len(document.get("materials", [])),
        "droppedBufferViews": dropped,
    }))


if __name__ == "__main__":
    main()
