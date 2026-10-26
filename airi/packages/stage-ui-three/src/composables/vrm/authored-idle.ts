import type { VRM } from '@pixiv/three-vrm'
import type { VRMHumanBoneName } from '@pixiv/three-vrm-core'
import type { Object3D } from 'three'

import { AnimationClip, Quaternion, QuaternionKeyframeTrack } from 'three'

/**
 * The upstream AIRI idle, reduced to the part another model can wear.
 *
 * The upstream project ships one authored idle for its own character, and
 * that file is the reason the character reads as a person: one coherent
 * movement for the whole figure, rather than a noise layer per bone.
 *
 * A .vrma cannot be handed to a different model as it stands.  It is a
 * hierarchy of synthetic nodes whose rest rotations are all identity, so
 * it carries *motion* and no pose -- there is nothing in it to copy, only
 * the way the pose changes.  What is worth keeping is the world-space
 * delta of every humanoid bone: how far that bone travels, and in which
 * direction, measured against the loop's own average pose.
 *
 * Those deltas are model independent, which is the whole point.  Given a
 * target rig, each delta is turned into a local bone rotation by
 * composing it with the target's own rest pose, and the target keeps its
 * own stance while moving the way the source moves.
 *
 * The result is the source's motion in world axes -- the sagittal,
 * frontal and transverse planes a person actually moves in -- so the
 * target's weight shift is a weight shift and its head turn is a head
 * turn, whatever shape it is.
 */

export interface AuthoredIdlePayload {
  name: string
  source: string
  duration: number
  /** base64 float32, one time per key */
  times: string
  /** base64 float32 quaternions, four per key, one entry per bone */
  bones: Record<string, string>
}

export interface AuthoredIdle {
  name: string
  duration: number
  times: Float32Array
  /** The world-space delta of each bone: one quaternion per key. */
  bones: Map<string, Float32Array>
}

function decodeFloats(base64: string): Float32Array {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index++)
    bytes[index] = binary.charCodeAt(index)
  // The buffer has to be a copy: `atob` gives us bytes that may not be
  // four-byte aligned, and a Float32Array over a misaligned buffer
  // throws in some engines.
  const copy = new Uint8Array(bytes.byteLength)
  copy.set(bytes)
  return new Float32Array(copy.buffer)
}

export function decodeAuthoredIdle(payload: AuthoredIdlePayload): AuthoredIdle {
  const bones = new Map<string, Float32Array>()
  for (const [name, values] of Object.entries(payload.bones))
    bones.set(name, decodeFloats(values))
  return {
    name: payload.name,
    duration: payload.duration,
    times: decodeFloats(payload.times),
    bones,
  }
}

/** What the target rig looked like before anything moved it. */
export interface AuthoredRest {
  /** The bone's own rest world rotation. */
  world: Quaternion
  /** The rest world rotation of the bone's scene parent. */
  parentWorld: Quaternion
  /**
   * The humanoid name of the scene parent, when the scene parent is
   * itself a driven bone.  The parent's motion has to be taken out of
   * the child's, or the parent would be counted twice.
   */
  parentName?: string
}

/**
 * Read the rig's rest pose.
 *
 * This has to happen before the mixer writes anything: once a clip has
 * run, the bones hold a pose and the rest pose is gone.  The scene calls
 * this while the model is still standing still.
 */
export function captureAuthoredRest(vrm: VRM, names: string[]): Map<string, AuthoredRest> {
  const rest = new Map<string, AuthoredRest>()
  const humanoid = vrm.humanoid
  if (!humanoid)
    return rest

  // The scene parent of a bone is usually the bone above it, and usually
  // the one the humanoid map calls its parent.  When they agree, the
  // parent's motion has to be divided out of the child's; when they do
  // not, the scene parent is just a frame and carries no motion.
  const byName = new Map<string, string>()
  for (const name of names) {
    const node = humanoid.getBoneNode(name as VRMHumanBoneName)
    if (node)
      byName.set(node.name, name)
  }

  vrm.scene.updateMatrixWorld(true)
  for (const name of names) {
    const node = humanoid.getBoneNode(name as VRMHumanBoneName)
    if (!node)
      continue
    const world = new Quaternion()
    node.getWorldQuaternion(world)
    const parent = node.parent as Object3D | undefined
    const parentWorld = new Quaternion()
    if (parent) {
      parent.updateWorldMatrix(true, false)
      parent.getWorldQuaternion(parentWorld)
    }
    rest.set(name, {
      world,
      parentWorld,
      parentName: parent ? byName.get(parent.name) : undefined,
    })
  }
  return rest
}

export interface AuthoredIdleClipOptions {
  /**
   * Bones the clip must not touch.
   *
   * The head is the usual one: it is solved against the gaze target, and
   * a clip that also wrote it would fight the solver every frame.
   */
  skip?: string[]
  /** How much of the source motion to keep. */
  gain?: number
}

/**
 * Turn the source's world-space motion into local bone rotations for the
 * target rig.
 *
 * The composition is the whole trick.  The source says how far a bone
 * travels in the world; the target has to be told how far to turn *its*
 * bone so that it travels the same way, which depends on where the bone
 * sits in the target and on what its parent is doing at that moment.
 */
export function buildAuthoredIdleClip(
  idle: AuthoredIdle,
  vrm: VRM,
  rest: Map<string, AuthoredRest>,
  options: AuthoredIdleClipOptions = {},
): AnimationClip | undefined {
  const humanoid = vrm.humanoid
  if (!humanoid)
    return undefined
  const skip = new Set(options.skip ?? [])
  const gain = options.gain ?? 1
  const keyCount = idle.times.length
  const tracks: QuaternionKeyframeTrack[] = []

  for (const [name, deltas] of idle.bones) {
    if (skip.has(name))
      continue
    const node = humanoid.getBoneNode(name as VRMHumanBoneName)
    const boneRest = rest.get(name)
    if (!node || !boneRest)
      continue
    if (deltas.length < keyCount * 4)
      continue

    const parentDeltas = boneRest.parentName ? idle.bones.get(boneRest.parentName) : undefined
    const values = new Float32Array(keyCount * 4)

    for (let key = 0; key < keyCount; key++) {
      // Where the bone's parent is, at this instant.
      const parentWorld = boneRest.parentWorld.clone()
      if (parentDeltas) {
        const parentDelta = new Quaternion(
          parentDeltas[key * 4],
          parentDeltas[key * 4 + 1],
          parentDeltas[key * 4 + 2],
          parentDeltas[key * 4 + 3],
        )
        parentWorld.premultiply(parentDelta)
      }

      // Where the bone has to be.
      const delta = new Quaternion(
        deltas[key * 4],
        deltas[key * 4 + 1],
        deltas[key * 4 + 2],
        deltas[key * 4 + 3],
      )
      if (gain !== 1) {
        const angle = 2 * Math.acos(Math.min(1, Math.abs(delta.w)))
        if (angle > 1e-6) {
          const scale = Math.sin(angle * 0.5 * gain) / Math.sin(angle * 0.5)
          delta.set(delta.x * scale, delta.y * scale, delta.z * scale, delta.w * scale).normalize()
        }
      }
      const world = boneRest.world.clone().premultiply(delta)

      // And which way its own bone has to turn to get there.
      const local = parentWorld.invert().multiply(world)
      values[key * 4] = local.x
      values[key * 4 + 1] = local.y
      values[key * 4 + 2] = local.z
      values[key * 4 + 3] = local.w
    }

    tracks.push(new QuaternionKeyframeTrack(
      `${node.name}.quaternion`,
      idle.times,
      values,
    ))
  }

  if (tracks.length === 0)
    return undefined
  return new AnimationClip(idle.name, idle.duration, tracks)
}
