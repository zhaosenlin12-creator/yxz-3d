/**
 * The motion system behind the 宜小智 desk pet.
 *
 * The figure is drawn as a layered 2D sprite on a canvas, so the character
 * cannot be "rigged" the way a 3D avatar is.  What it can be is *directed*:
 * every channel below is a single scalar that the renderer adds on top of
 * the breathing pose, and every action is a small choreography that writes
 * into those channels over time.
 *
 * The vocabulary comes from classic hand-drawn animation rather than from a
 * physics engine:
 *
 *   - **anticipation** — a move winds up before it fires, so the jump has
 *     somewhere to come from;
 *   - **squash and stretch** — the body deforms along the axis of the
 *     movement instead of sliding rigidly;
 *   - **follow-through** — the landing overshoots and settles back with an
 *     elastic curve rather than stopping dead;
 *   - **overlapping action** — the eyes answer the body, so nothing arrives
 *     at the same instant.
 *
 * One constraint shapes the whole vocabulary: the helmet and the halo are
 * welded into the body picture, so the head cannot turn on its own.  A
 * "head tilt" therefore has to be read off the *body* rotation and the
 * eyes sliding inside the visor, not off a rotated face.
 *
 * The easing and the timelines come from anime.js v4, which the studio
 * already depends on.
 */
import { animate, createTimeline, utils } from 'animejs'

export type YXZPetStatus
  = | 'idle'
    | 'listening'
    | 'thinking'
    | 'speaking'
    | 'processing'
    | 'success'

/**
 * The channels the canvas renderer reads.  Units are art pixels and
 * radians so that a value means the same thing at every stage size.
 */
export interface YXZPetChannels {
  /** Vertical lift, positive is up. */
  lift: number
  /** Horizontal lean. */
  lean: number
  /** Body rotation. */
  bodyRot: number
  /** How far the face slides inside the visor, in art pixels. */
  faceOffsetX: number
  faceOffsetY: number
  /** Horizontal squash-and-stretch multiplier. */
  squashX: number
  /** Vertical squash-and-stretch multiplier. */
  squashY: number
  /** Extra halo brightness, 0 is the resting glow. */
  glow: number
  /** Eye openness multiplier, 1 is fully open. */
  eyeOpen: number
  /** Gaze bias added on top of the tracked pointer. */
  gazeBiasX: number
  gazeBiasY: number
  /** High frequency jitter, used while work is running. */
  shake: number
  /** Brightness of the sparkles that come off the waving hand. */
  handSpark: number
}

function makeChannels(): YXZPetChannels {
  return {
    lift: 0,
    lean: 0,
    bodyRot: 0,
    faceOffsetX: 0,
    faceOffsetY: 0,
    squashX: 1,
    squashY: 1,
    glow: 0,
    eyeOpen: 1,
    gazeBiasX: 0,
    gazeBiasY: 0,
    shake: 0,
    handSpark: 0,
  }
}

/** The resting pose each status settles into. */
const POSES: Record<YXZPetStatus, YXZPetChannels> = {
  // Standing at ease, breathing, ready for the next question.
  idle: makeChannels(),
  // Leaning in a little: the character is paying attention.
  listening: {
    ...makeChannels(),
    lift: 5,
    bodyRot: 0.014,
    squashY: 1.018,
    glow: 0.18,
    eyeOpen: 1.1,
  },
  // The weight shifts and the eyes turn away: the character is working
  // something out.
  thinking: {
    ...makeChannels(),
    lean: -3,
    bodyRot: -0.026,
    faceOffsetX: -3,
    faceOffsetY: -6,
    squashX: 1.012,
    glow: -0.18,
    eyeOpen: 0.74,
    gazeBiasX: -0.42,
    gazeBiasY: -0.34,
  },
  // Up and forward, the way a body leans into its own sentence.
  speaking: {
    ...makeChannels(),
    lift: 4,
    lean: 2,
    squashY: 1.012,
    glow: 0.22,
    eyeOpen: 1.06,
  },
  // Weight shifted, a fine tremor, the halo running hot.
  processing: {
    ...makeChannels(),
    bodyRot: 0.01,
    glow: 0.34,
    eyeOpen: 0.9,
    gazeBiasY: 0.24,
    shake: 1.1,
  },
  // Brighter than usual, eyes wide open.
  success: {
    ...makeChannels(),
    glow: 0.5,
    eyeOpen: 1.14,
  },
}

/** How long the character waits before the next idle flourish. */
const FLOURISH_MIN_MS = 4200
const FLOURISH_MAX_MS = 9600

export interface YXZPetMotion {
  /** The live channels.  Read them every frame; never replace the object. */
  channels: YXZPetChannels
  /** Move to a new status, easing into its resting pose. */
  setStatus: (status: YXZPetStatus) => void
  /** Fire a one-off action on top of the current pose. */
  play: (action: YXZPetFlourish) => void
  /** Freeze everything, including the timelines in flight. */
  pause: () => void
  /** Resume after a pause. */
  resume: () => void
  /** Release timers and animations. */
  destroy: () => void
}

/** The one-off actions the character can play on its own. */
export type YXZPetFlourish
  = | 'sparkle'
    | 'tilt'
    | 'hop'
    | 'look-around'
    | 'nod'
    | 'stretch'
    | 'peek'
    | 'bounce'
    | 'shrug'
    | 'celebrate'

const FLOURISHES: YXZPetFlourish[] = [
  'sparkle',
  'tilt',
  'hop',
  'look-around',
  'nod',
  'stretch',
  'peek',
  'bounce',
  'shrug',
]

export function createYXZPetMotion(): YXZPetMotion {
  const channels = makeChannels()
  let status: YXZPetStatus = 'idle'
  let flourishTimer: ReturnType<typeof setTimeout> | undefined
  let paused = false

  /**
   * Every animation started here, so a pause can freeze the ones that are
   * still in flight and a status change can clear the ones that no longer
   * apply.
   */
  const running = new Set<{ pause: () => void, play: () => void }>()

  function track<T extends { pause: () => void, play: () => void }>(animation: T) {
    running.add(animation)
    if (paused)
      animation.pause()
    return animation
  }

  function clearAnimations() {
    utils.remove(channels)
    running.clear()
  }

  // --- the one-off actions ------------------------------------------------

  /**
   * A jump: wind up, launch, fall, land, settle.  Each beat uses a
   * different easing so the move reads as four beats instead of one.
   */
  function hop(strength = 1) {
    const lift = 52 * strength
    track(createTimeline()
      .add(channels, {
        squashY: [1, 0.84],
        squashX: [1, 1.14],
        duration: 130,
        ease: 'outQuad',
      })
      .add(channels, {
        squashY: [0.84, 1.2],
        squashX: [1.14, 0.88],
        lift: [0, -lift * 0.72],
        duration: 260,
        ease: 'outQuad',
      })
      .add(channels, {
        lift: [-lift * 0.72, 0],
        duration: 300,
        ease: 'inQuad',
      })
      .add(channels, {
        squashY: [1.2, 0.8],
        squashX: [0.88, 1.18],
        duration: 110,
        ease: 'outQuad',
      })
      .add(channels, {
        squashY: [0.8, 1],
        squashX: [1.18, 1],
        duration: 480,
        ease: 'outElastic(1, .45)',
      }))
  }

  /**
   * The greeting: the hand lights up and a burst of stars comes off the
   * glove while the halo answers a little brighter.
   *
   * The arm does not move.  It is one piece with the body, and a piece
   * that is cut out and turned around a joint opens a seam at that
   * joint; the light on the hand is what carries the greeting instead.
   */
  function sparkle() {
    track(createTimeline()
      .add(channels, {
        handSpark: [channels.handSpark, 1],
        glow: [channels.glow, 0.62],
        duration: 180,
        ease: 'outQuad',
      })
      .add(channels, {
        handSpark: [1, 0],
        glow: [0.62, channels.glow],
        duration: 620,
        ease: 'outElastic(1, .5)',
      }))
  }

  /** Curiosity: the body tips over and the eyes go with it. */
  function tilt() {
    const side = Math.random() > 0.5 ? 1 : -1
    track(createTimeline()
      .add(channels, {
        bodyRot: [channels.bodyRot, 0.13 * side],
        lean: [channels.lean, 5 * side],
        faceOffsetX: [channels.faceOffsetX, 6 * side],
        gazeBiasX: [channels.gazeBiasX, 0.3 * side],
        squashX: [channels.squashX, 1.02],
        duration: 420,
        ease: 'outBack',
      })
      .add(channels, {
        bodyRot: 0.13 * side,
        lean: 5 * side,
        faceOffsetX: 6 * side,
        gazeBiasX: 0.3 * side,
        duration: 900,
        ease: 'inOutSine',
      })
      .add(channels, {
        bodyRot: [0.13 * side, 0],
        lean: [5 * side, 0],
        faceOffsetX: [6 * side, 0],
        gazeBiasX: [0.3 * side, 0],
        squashX: [1.02, 1],
        duration: 520,
        ease: 'outElastic(1, .55)',
      }))
  }

  /** A nod: the body dips and comes back, the eyes dip with it. */
  function nod() {
    track(createTimeline()
      .add(channels, { squashY: [1, 1.05], faceOffsetY: [0, 7], gazeBiasY: [0, 0.35], duration: 190, ease: 'outQuad' })
      .add(channels, { squashY: [1.05, 0.97], faceOffsetY: [7, -2], gazeBiasY: [0.35, -0.05], duration: 170, ease: 'inQuad' })
      .add(channels, { squashY: [0.97, 1.04], faceOffsetY: [-2, 6], gazeBiasY: [-0.05, 0.3], duration: 190, ease: 'outQuad' })
      .add(channels, { squashY: [1.04, 1], faceOffsetY: [6, 0], gazeBiasY: [0.3, 0], duration: 320, ease: 'outElastic(1, .5)' }))
  }

  /** A lazy stretch: tall and thin, then back to normal. */
  function stretch() {
    track(createTimeline()
      .add(channels, {
        squashY: [1, 1.09],
        squashX: [1, 0.94],
        lift: [channels.lift, 9],
        duration: 620,
        ease: 'outQuad',
      })
      .add(channels, {
        squashY: [1.09, 1],
        squashX: [0.94, 1],
        lift: [9, channels.lift],
        duration: 700,
        ease: 'outElastic(1, .5)',
      }))
  }

  /** The eyes sweep the room and come back. */
  function lookAround() {
    track(createTimeline()
      .add(channels, { gazeBiasX: [0, -0.75], gazeBiasY: [0, -0.1], duration: 380, ease: 'inOutSine' })
      .add(channels, { gazeBiasX: [-0.75, 0.75], gazeBiasY: [-0.1, -0.25], duration: 620, ease: 'inOutSine' })
      .add(channels, { gazeBiasX: [0.75, 0], gazeBiasY: [-0.25, 0], duration: 420, ease: 'outQuad' }))
  }

  /**
   * Peeking: the figure slides out from behind its own shoulder to see
   * what is going on, holds the peek, and then slips back.  The hold is
   * what makes it read as curiosity instead of as a twitch.
   */
  function peek() {
    const side = Math.random() > 0.5 ? 1 : -1
    track(createTimeline()
      .add(channels, {
        lean: [channels.lean, 9 * side],
        bodyRot: [channels.bodyRot, 0.05 * side],
        faceOffsetX: [channels.faceOffsetX, 9 * side],
        gazeBiasX: [channels.gazeBiasX, 0.55 * side],
        lift: [channels.lift, 4],
        duration: 380,
        ease: 'outBack',
      })
      .add(channels, {
        lean: 9 * side,
        bodyRot: 0.05 * side,
        faceOffsetX: 9 * side,
        gazeBiasX: 0.55 * side,
        lift: 4,
        duration: 620,
        ease: 'inOutSine',
      })
      .add(channels, {
        lean: [9 * side, 0],
        bodyRot: [0.05 * side, 0],
        faceOffsetX: [9 * side, 0],
        gazeBiasX: [0.55 * side, 0],
        lift: [4, 0],
        duration: 520,
        ease: 'outElastic(1, .6)',
      }))
  }

  /**
   * Bouncing: two small hops in a row, the way a character that cannot
   * sit still answers a good idea.  The second hop is smaller, which is
   * what makes the pair look like one gesture instead of two.
   */
  function bounce() {
    const small = () => track(createTimeline()
      .add(channels, { squashY: [1, 0.9], squashX: [1, 1.09], duration: 100, ease: 'outQuad' })
      .add(channels, { squashY: [0.9, 1.1], squashX: [1.09, 0.95], lift: [0, -26], duration: 170, ease: 'outQuad' })
      .add(channels, { lift: [-26, 0], duration: 190, ease: 'inQuad' })
      .add(channels, { squashY: [1.1, 0.9], squashX: [0.95, 1.08], duration: 80, ease: 'outQuad' })
      .add(channels, { squashY: [0.9, 1], squashX: [1.08, 1], duration: 300, ease: 'outElastic(1, .5)' }))
    track(createTimeline()
      .add(channels, { glow: [channels.glow, channels.glow + 0.25], duration: 180, ease: 'outQuad' }))
    small()
    setTimeout(() => {
      if (!paused)
        small()
    }, 320)
  }

  /**
   * A shrug: the small "I have no idea" of the shoulders, told with the
   * whole body because the picture has no arms of its own.
   */
  function shrug() {
    track(createTimeline()
      .add(channels, {
        lift: [channels.lift, 7],
        squashY: [1, 1.045],
        squashX: [1, 1.035],
        bodyRot: [channels.bodyRot, -0.022],
        eyeOpen: [channels.eyeOpen, 1.16],
        duration: 320,
        ease: 'outBack',
      })
      .add(channels, {
        lift: [7, 4],
        bodyRot: [-0.022, 0.024],
        duration: 260,
        ease: 'inOutSine',
      })
      .add(channels, {
        lift: [4, 0],
        bodyRot: [0.024, 0],
        squashY: [1.045, 1],
        squashX: [1.035, 1],
        eyeOpen: [1.16, 1],
        duration: 480,
        ease: 'outElastic(1, .55)',
      }))
  }

  /** The big finish: a jump with the halo flaring on the take off. */
  function celebrate() {
    track(createTimeline()
      .add(channels, {
        glow: [channels.glow, 1],
        squashY: [1, 0.82],
        squashX: [1, 1.16],
        duration: 150,
        ease: 'outQuad',
      })
      .add(channels, {
        squashY: [0.82, 1.22],
        squashX: [1.16, 0.86],
        lift: [0, -64],
        bodyRot: [0, -0.12],
        // The hand throws off its stars on the way up, so the finish
        // reads as a greeting rather than as a hop.
        handSpark: [channels.handSpark, 0.85],
        duration: 280,
        ease: 'outQuad',
      })
      .add(channels, {
        lift: [-64, 0],
        bodyRot: [-0.12, 0.1],
        duration: 320,
        ease: 'inQuad',
      })
      .add(channels, {
        bodyRot: [0.1, 0],
        squashY: [1.22, 0.8],
        squashX: [0.86, 1.18],
        duration: 110,
        ease: 'outQuad',
      })
      .add(channels, {
        squashY: [0.8, 1],
        squashX: [1.18, 1],
        glow: [1, 0],
        handSpark: [0.85, 0],
        duration: 620,
        ease: 'outElastic(1, .45)',
      }))
  }

  function play(action: YXZPetFlourish) {
    if (paused)
      return
    switch (action) {
      case 'sparkle':
        sparkle()
        break
      case 'tilt':
        tilt()
        break
      case 'hop':
        hop()
        break
      case 'look-around':
        lookAround()
        break
      case 'nod':
        nod()
        break
      case 'stretch':
        stretch()
        break
      case 'peek':
        peek()
        break
      case 'bounce':
        bounce()
        break
      case 'shrug':
        shrug()
        break
      case 'celebrate':
        celebrate()
        break
    }
  }

  // --- the status poses ----------------------------------------------------

  function setStatus(next: YXZPetStatus) {
    if (next === status)
      return
    status = next
    clearAnimations()
    const pose = POSES[next]
    channels.lift = pose.lift
    channels.lean = pose.lean
    channels.bodyRot = pose.bodyRot
    channels.faceOffsetX = pose.faceOffsetX
    channels.faceOffsetY = pose.faceOffsetY
    channels.squashX = pose.squashX
    channels.squashY = pose.squashY
    channels.glow = pose.glow
    channels.eyeOpen = pose.eyeOpen
    channels.gazeBiasX = pose.gazeBiasX
    channels.gazeBiasY = pose.gazeBiasY
    channels.shake = pose.shake
    channels.handSpark = 0

    if (paused)
      return

    // The character eases into the new pose rather than snapping into it.
    track(animate(channels, {
      lift: pose.lift,
      lean: pose.lean,
      bodyRot: pose.bodyRot,
      faceOffsetX: pose.faceOffsetX,
      faceOffsetY: pose.faceOffsetY,
      squashX: pose.squashX,
      squashY: pose.squashY,
      glow: pose.glow,
      eyeOpen: pose.eyeOpen,
      gazeBiasX: pose.gazeBiasX,
      gazeBiasY: pose.gazeBiasY,
      shake: pose.shake,
      handSpark: 0,
      duration: 460,
      ease: 'outElastic(1, .8)',
    }))

    // Two statuses breathe on their own: the loop is the part of the pose
    // that never settles.
    if (next === 'processing') {
      track(animate(channels, {
        glow: [pose.glow, pose.glow + 0.45],
        duration: 620,
        loop: true,
        alternate: true,
        ease: 'inOutSine',
      }))
    }
    if (next === 'thinking') {
      track(animate(channels, {
        squashY: [pose.squashY, pose.squashY - 0.03],
        duration: 1500,
        loop: true,
        alternate: true,
        ease: 'inOutSine',
      }))
    }
    if (next === 'success') {
      celebrate()
    }
  }

  // --- the idle flourishes -------------------------------------------------

  function scheduleFlourish() {
    if (flourishTimer)
      clearTimeout(flourishTimer)
    const delay = FLOURISH_MIN_MS + Math.random() * (FLOURISH_MAX_MS - FLOURISH_MIN_MS)
    flourishTimer = setTimeout(() => {
      // A busy character does not fidget, and a character that is mid
      // sentence keeps its attention on the visitor.
      if (!paused && status === 'idle') {
        const action = FLOURISHES[Math.floor(Math.random() * FLOURISHES.length)]
        play(action)
      }
      scheduleFlourish()
    }, delay)
  }

  scheduleFlourish()

  function pause() {
    if (paused)
      return
    paused = true
    if (flourishTimer)
      clearTimeout(flourishTimer)
    for (const animation of running)
      animation.pause()
  }

  function resume() {
    if (!paused)
      return
    paused = false
    for (const animation of running)
      animation.play()
    scheduleFlourish()
  }

  function destroy() {
    if (flourishTimer)
      clearTimeout(flourishTimer)
    flourishTimer = undefined
    clearAnimations()
    utils.remove(channels)
  }

  return { channels, setStatus, play, pause, resume, destroy }
}
