<script setup lang="ts">
import type { VRM } from '@pixiv/three-vrm'

import type { AuthoredRest } from '../composables/vrm/authored-idle'
import type { YXZStatus } from './yxz-status'

import { VRMUtils } from '@pixiv/three-vrm'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js'
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js'
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js'
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import * as THREE from 'three'

import authoredIdlePayload from '../assets/vrm/animations/yxz-idle-authored.json'
import yxzVrmUrl from '../assets/vrm/models/yxz.vrm?url'

import {
  buildAuthoredIdleClip,
  captureAuthoredRest,
  decodeAuthoredIdle,
} from '../composables/vrm/authored-idle'
import { loadVrm } from '../composables/vrm/core'
import { useVRMEmote } from '../composables/vrm/expression'

export type { YXZStatus }

const props = withDefaults(defineProps<{
  status?: YXZStatus
  speakingLevel?: number
  paused?: boolean
  src?: string
}>(), {
  status: 'idle',
  speakingLevel: 0,
  paused: false,
  src: yxzVrmUrl,
})

const emit = defineEmits<{
  error: [error: unknown]
}>()

const componentState = defineModel<'pending' | 'loading' | 'mounted'>('state', { default: 'pending' })
const canvasContainer = ref<HTMLDivElement>()
const activeLabel = computed(() => ({
  idle: '你好，我是宜小智，想做什么？',
  listening: '我在认真听你的想法',
  thinking: '我正在理解并整理方案',
  speaking: '我来向你介绍这份方案',
  processing: '我正在生成预览和 3D 模型',
  success: '方案完成，可以继续编辑或下载',
}[props.status]))
const isSpeaking = computed(() => props.status === 'speaking')

let renderer: THREE.WebGLRenderer | undefined
let scene: THREE.Scene | undefined
let camera: THREE.PerspectiveCamera | undefined
let actor: THREE.Group | undefined
let composer: EffectComposer | undefined
let outlinePass: ShaderPass | undefined
let bloomPass: UnrealBloomPass | undefined
let vrm: VRM | undefined
let vrmGroup: THREE.Group | undefined
let mixer: THREE.AnimationMixer | undefined
let activeAction: THREE.AnimationAction | undefined
// The authored idle, playing underneath whatever the state is doing.
let authoredAction: THREE.AnimationAction | undefined
// The rig's rest pose, as the idle was retargeted onto it.
let authoredRest: Map<string, AuthoredRest> | undefined
let emote: ReturnType<typeof useVRMEmote> | undefined
const actionMap = new Map<string, THREE.AnimationAction>()
// Which bones the active clip holds still; see constantRotationBones.
const clipStillBones = new Map<string, Set<string>>()
// Which bones the active clip has had taken away entirely, and which the
// living layer therefore owns outright.
const clipOwnedBones = new Map<string, Set<string>>()
let animationFrame = 0
let resizeObserver: ResizeObserver | undefined
let reducedMotion = false
let motionQuery: MediaQueryList | undefined
let motionListener: ((event: MediaQueryListEvent) => void) | undefined
let lastFrameAt = 0
// How fast the character's own clock runs, relative to the wall clock.
//
// It is one in the page and it is only ever something else from the
// debug hook below, which exists because the headless browser this was
// tuned in draws the stage at about a frame a second, and a capture of
// the living layer taken at that rate covers three seconds of a
// two-minute idle.  The hook scales the clock so a capture can be
// asked for the two minutes rather than the three seconds.
let lifeTimeScale = 1
let animatedModel: THREE.Object3D | undefined
const baselineWorldSize = new THREE.Vector3()
let lastBoundsCheckAt = 0
let motionGuardTriggered = false
let loadToken = 0
let frameCount = 0
// Entrance animation: the character floats up and settles with a small bounce
// once, right after the model mounts. -1 = not started, >=0 = running (start
// wall-clock ms), -2 = finished.
let introStart = -1
// The entrance is applied to the vrm group's own scale (multiplicative), so it
// never fights the actor scale chosen by fitActor.
const INTRO_DURATION_MS = 1150
// Dev-only: lets the QA capture script park the clip on an exact frame so
// the screenshots are reproducible instead of depending on how many frames
// the headless renderer managed to draw.
let poseFrozen = false

const cameraWorldPosition = new THREE.Vector3()

/*
 * Silhouette outline.
 *
 * The VRM's own MToon outline cannot be used on this asset.  That technique
 * draws the mesh's back faces pushed out along the vertex normals, which only
 * reads as a line when the mesh is a closed shell of uniform thickness.  The
 * Tripo body is a merge of many sheets that carry real interior surfaces --
 * the helmet liner, the panel seams, the inside of the ear cups -- and
 * measuring the exported GLB, 43% of the shell's triangles face away from the
 * camera.  Every one of those sheets leaks ink across the character: the
 * helmet rim drew a band across the chin and each seam drew a line over the
 * body, which together read as a grey veil rather than an outline.  That is
 * a property of the geometry, so no width factor tunes it away.
 *
 * three's `OutlinePass` is no good either.  It finds edges by looking for
 * discontinuities in the depth buffer, which is exactly the wrong signal for
 * this mesh: every interior sheet that sits under the outer skin shows up as
 * a depth step, so the pass drew a line along every panel seam and the
 * character read as a pile of shards.  On top of that, r183 runs the
 * detection on a mask that is downsampled by `downSampleRatio` (2), so a
 * one-pixel antenna is half a pixel by the time it is measured and the line
 * breaks into dashes.
 *
 * What a toon character actually wants is one clean line around the outside,
 * and the outside is easy to get: the renderer draws the character on a
 * transparent background, so the beauty pass already carries the silhouette
 * in its alpha channel.  Dilating that alpha by a pixel and inking the
 * difference gives a continuous line of even weight, with no dashes, no
 * interior seams, and none of the character's own pixels covered.
 */
// The ink is not ink.  On the reference the character is a bright white
// shell on a white ground and there is no line drawn round it at all --
// what separates it from the page is the shading on the shell and a soft
// occlusion under the chin.  A drawn line can only add something here,
// and what it added was a hard dark contour round every piece of a model
// that is stitched from a hundred of them, which is where the shattered
// look came from.  So what is drawn instead is a cool grey-blue shadow
// that sits *outside* the silhouette and fades away from it: the read is
// of a figure lit from above and standing on a pale page, not of a
// sticker with a border.
const OUTLINE_COLOR = 0x8FA6C2
// How much of that shadow goes into the tight line at the edge, and how
// much into the wide skirt that fades out around it.  The line is what
// keeps a white character findable on a white page; the skirt is what
// keeps it from looking like it was cut out with scissors.
const OUTLINE_LINE = 0.55
const OUTLINE_SKIRT = 0.42
// Width of the line in CSS pixels; the shader scales it by the device pixel
// ratio so the ink reads the same on a retina screen as on a desktop one.
const OUTLINE_WIDTH = 0.9

// How far the shader looks for the background when it decides whether a
// gap in the shell is a crack or the character's own edge, and how close
// the shell has to be for the gap to be a crack at all.  In device pixels:
// a crack in the shell is a couple of pixels wide and the shell is right
// there on either side of it, while the space between the arm and the
// body opens out to the background in half the directions.
//
// The reach is short on purpose.  The visor is a dish sunk into the
// helmet and the gap round its rim is a real opening that the page shows
// through, so the corridor test read it as the edge of the character and
// drew a ragged black line all the way round the visor -- a broken edge
// on the one clean line the face has.  A crack in the shell is two or
// three pixels wide, so a reach of a few pixels finds the shell again
// long before it finds the world.
const OUTLINE_REACH = 7
const OUTLINE_FILL = 3

// How many of the twelve directions have to reach the world before a gap
// counts as the edge of the character.  Three was low enough that a seam
// running straight for twenty pixels found enough "background" along its
// own length to be inked, and every tile boundary in the scan has a seam
// running along it.  Five is above what a bounded gap can reach and below
// what a real silhouette reaches, which is the whole difference between
// one line round the character and a net of lines across it.
const OUTLINE_OPEN = 5

// How far the shader looks for the surface when it closes a crack.  The
// crack in the shell is a couple of pixels across, so the surface it
// belongs to is never far away; a small radius is enough and it keeps
// the colour that closes the crack from bleeding across the edge of a
// panel.
const OUTLINE_SEAL = 9

// How much the colour that closes a crack is pulled towards the ink.
// A crack is a crease in the surface, not a hole in it: closing it with
// the colour of the shell around it, a little darker, reads as a crease.
// Closing it with the page's own colour reads as a hole.
//
// The amount is small on purpose.  The scan's tiles do not quite meet,
// and the hairline where they do not is closed here rather than in the
// geometry; at a fifth of the way to the ink every one of those
// hairlines was a dark line drawn across the white shell, and a white
// shell with a hundred dark lines across it is the shattered look this
// whole pass exists to remove.  At this much the gap is closed and the
// surface carries on.
const OUTLINE_CREASE = 0.07

// The glow.  `BLOOM_THRESHOLD` is measured in the linear buffer the
// composer keeps, where the white shell sits at about 1.3 and the halo is
// pushed to about 1.2 in its brightest blue, so the threshold sits between
// the two and only the light spills.
const BLOOM_THRESHOLD = 1.55
const BLOOM_STRENGTH = 0.95
const BLOOM_RADIUS = 0.65

// The halo is the one thing on this character that is light rather than
// surface, and a ring of geometry is still a ring of geometry to a pass
// that reads the silhouette: given one it will draw a line round it, and
// a glowing ring with a dark line round it is a length of wire.  The
// halo marks its own pixels -- a material patch writes a fixed alpha
// there instead of the coverage a surface writes -- and this pass reads
// that mark and leaves those pixels out of the silhouette entirely.
//
// The alpha alone cannot carry it.  A partly covered pixel at the edge of
// any surface has an alpha somewhere in between, and the shell is full of
// edges.  What no other pixel on the character has is the halo's colour:
// a saturated cyan that is well above black in its brightest channel.  So
// the test is a half-covered alpha *and* that colour, and the shell --
// white, warm where the key lands on it and cool where the sky fills it
// -- never satisfies the second half.
const HALO_SATURATION = 0.62
const HALO_PEAK = 0.30

const OUTLINE_SHADER = {
  name: 'YXZSilhouetteOutline',
  uniforms: {
    tDiffuse: { value: null as THREE.Texture | null },
    uTexel: { value: new THREE.Vector2(1 / 1024, 1 / 1024) },
    uRadius: { value: 1.5 },
    uInk: { value: new THREE.Color(OUTLINE_COLOR) },
    uLine: { value: OUTLINE_LINE },
    uSkirt: { value: OUTLINE_SKIRT },
    // How deep the silhouette is measured.  Zero reads the alpha as it is;
    // one reads it three pixels in, which is what stops the ink from
    // finding the scraps of torn shell lying on the character.
    uErode: { value: 1 },
    // How far away the background has to be for a gap to count as open to
    // the world rather than as a crack inside the character.
    uReach: { value: OUTLINE_REACH },
    // How close the shell has to be for a gap to be a crack in it.
    uFill: { value: OUTLINE_FILL },
    // How far the shader looks for the surface that closes a crack.
    uSeal: { value: OUTLINE_SEAL },
    // How much the colour closing a crack is pulled towards the ink.
    uCrease: { value: OUTLINE_CREASE },
    uOpen: { value: OUTLINE_OPEN },
    uHalo: { value: new THREE.Vector2(HALO_SATURATION, HALO_PEAK) },
  },
  vertexShader: /* glsl */`
    varying vec2 vUv;

    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
    }
  `,
  fragmentShader: /* glsl */`
    uniform sampler2D tDiffuse;
    uniform vec2 uTexel;
    uniform float uRadius;
    uniform vec3 uInk;
    uniform float uLine;
    uniform float uSkirt;
    uniform float uErode;
    uniform float uReach;
    uniform float uFill;
    uniform float uSeal;
    uniform float uCrease;
    uniform float uOpen;
    uniform vec2 uHalo;
    varying vec2 vUv;

    // Whether this pixel is one of the halo's.  Its own patch writes a
    // fixed alpha rather than a coverage, so the pixel is half covered by
    // definition, and the colour it wrote is a saturated cyan that the
    // shell never reaches.
    float isHalo( vec4 c ) {
      float peak = max( max( c.r, c.g ), c.b );
      float floorC = min( min( c.r, c.g ), c.b );
      float saturation = ( peak - floorC ) / max( peak, 1e-4 );
      return step( 0.03, c.a ) * ( 1.0 - step( 0.97, c.a ) )
        * step( uHalo.x, saturation ) * step( uHalo.y, peak );
    }

    // Coverage of the character itself.  The halo is left out of it on
    // purpose: the halo is not part of the silhouette, and if it were,
    // this pass would find its edge and draw the line round it that makes
    // a ring of light look like a piece of bent wire.
    float coverage( vec2 uv ) {
      vec4 c = texture2D( tDiffuse, uv );
      return step( 0.5, c.a ) * ( 1.0 - isHalo( c ) );
    }

    void main() {
      vec4 base = texture2D( tDiffuse, vUv );

      // The shell of this model is a scan stitched from a hundred separate
      // pieces, and the pieces do not quite meet: the boundary between two
      // of them is an open edge, and the background shows through it.  On
      // its own that is a hairline crack.  What made it read as shattered
      // glass was the line: the ink was drawn round every gap in the
      // silhouette, and a head with a hundred hairline cracks in it came
      // out with a hundred black lines drawn round them, which is exactly
      // what broken glass looks like.
      //
      // So the two are told apart.  The edge of the character opens out to
      // the background through a whole quarter of the directions around it;
      // a crack in the shell opens out through one or two.  A gap that is
      // open to the world gets the line, and a gap that is closed gets
      // the colour of the surface round it and a little of the ink, so it
      // reads as a crease in the shell rather than as a hole through it.
      float outer = 0.0;
      float inner = 0.0;
      float skirt = 0.0;
      float corridor = 0.0;
      for ( int i = 0; i < 12; i++ ) {
        float angle = float( i ) * 0.5235987756;
        vec2 dir = vec2( cos( angle ), sin( angle ) );

        // Two rings of taps.  The outer ring sets the line's outside edge,
        // the inner one fills the gaps the outer ring leaves on convex
        // corners, so the line stays unbroken all the way round the
        // silhouette.
        //
        // The tap is not a single sample.  The shell is a layer one
        // surface thick, and where the scan tore it there are slivers of
        // it standing proud of the body -- a pixel or two wide, with the
        // background showing on either side.  A single sample reads the
        // sliver as a silhouette, and the line is drawn round it as if it
        // were the character's edge, which turns every sliver into a dark
        // dot.  Reading the alpha three pixels in finds the body behind
        // the sliver instead.
        float far = coverage( vUv + dir * uTexel * uRadius );
        float near = coverage( vUv + dir * uTexel * uRadius * 0.45 );
        if ( uErode > 0.5 ) {
          far = min( far, coverage( vUv + dir * uTexel * ( uRadius + 1.0 ) ) );
          far = min( far, coverage( vUv + dir * uTexel * ( uRadius + 2.0 ) ) );
          near = min( near, coverage( vUv + dir * uTexel * ( uRadius * 0.45 + 1.0 ) ) );
        }
        outer = max( outer, far );
        inner = max( inner, near );

        // The soft skirt reaches much further out than the line does, and
        // it is what the white character actually needs on a white page:
        // a wide, weak shadow that fades away from the silhouette reads as
        // the figure sitting in the light, where a hard line reads as a
        // border drawn round it.  It is sampled once, at four times the
        // line's radius, so it costs the loop one more read.
        skirt = max( skirt, coverage( vUv + dir * uTexel * ( uRadius * 4.2 + 2.0 ) ) );

        // The corridor test.
        //
        // A gap in the shell is one of two things.  It is either a hole
        // *through* the character -- the space between the arm and the
        // body, the notch under the chin -- in which case the background
        // is there in this direction and it is still there a good way
        // further out, so the character has a real edge.  Or it is a
        // crack *in* the shell, where two pieces of the scan meet without
        // quite touching: the background is there, but only for as wide as
        // the crack is, so a short way further along the same direction
        // the shell is back.
        //
        // Asking for the background in the *same* direction at two
        // distances is what tells the two apart.  The old test only asked
        // whether the background was there at all, which is true of every
        // crack in the head, and that is why a seam between two pieces of
        // the scan was inked as if it were the character's outline: a
        // crown of hairlines came out looking like broken glass.
        if ( coverage( vUv + dir * uTexel * uFill ) < 0.5
          && coverage( vUv + dir * uTexel * uReach ) < 0.5 )
          corridor += 1.0;
      }
      outer = max( outer, inner );

      // Whether a pixel belongs to the character has to be a yes or a no.
      // The scan has a thin lip along the top of the visor that is almost
      // edge on to the camera, so its coverage is fractional and it varies
      // from pixel to pixel.  Treated as a fraction, those pixels let the
      // page behind the canvas show through and the lip breaks into white
      // speckle; treated as a half-covered pixel, the outline pass also
      // inks them from the inside and the lip breaks into dark speckle.
      // Thresholding once fixes both, and the silhouette itself keeps its
      // soft edge because the ink is drawn around it, not on it.
      // The halo counts as being *inside* something, so no line is drawn
      // across it, but the coverage test above leaves it out, so it is
      // never the thing a line is drawn round.
      float centre = max( step( 0.5, coverage( vUv ) ), isHalo( base ) );

      // Whether the gap this pixel is in is open to the world.  A third
      // of the directions reaching the background and still reaching it
      // further out is the edge of the character; fewer than that is a
      // crack inside it.
      float isOpen = step( uOpen, corridor );

      // The ink goes *outside* the silhouette, so the character keeps the
      // exact size the mesh has and only the empty pixels around it change.
      float ring = clamp( outer - centre, 0.0, 1.0 ) * isOpen;
      float shade = clamp( skirt - centre, 0.0, 1.0 ) * isOpen;

      // A crack is closed with the colour of the surface round it.
      //
      // The colour is taken from the *nearest* surface along each of a
      // few directions rather than from a ring of samples at a fixed
      // radius, so a crack on the dark visor is closed with the visor's
      // own colour and a crack on the white shell is closed with the
      // shell's.  Averaging the ring instead mixed the two, and a bright
      // hairline came out of every seam on the face.
      vec3 tint = vec3( 0.0 );
      float tintWeight = 0.0;
      float sealHalo = 0.0;
      if ( centre < 0.5 ) {
        for ( int i = 0; i < 8; i++ ) {
          float angle = float( i ) * 0.7853981634 + 0.39;
          vec2 dir = vec2( cos( angle ), sin( angle ) );
          for ( int s = 1; s <= 12; s++ ) {
            vec4 hit = texture2D( tDiffuse, vUv + dir * uTexel * ( uSeal / 12.0 ) * float( s ) );
            // A halo is found here and left alone.  Closing the space
            // around the ring with the colour of the shell would paint a
            // white patch on the page either side of it, which is worse
            // than the gap it was closing.
            if ( isHalo( hit ) > 0.5 ) {
              sealHalo = 1.0;
              break;
            }
            if ( hit.a > 0.5 ) {
              float w = 1.0 / float( s );
              tint += hit.rgb * w;
              tintWeight += w;
              break;
            }
          }
        }
      }
      // The closed crack is pulled a little towards the ink so that it
      // reads as a crease in the surface rather than as a smear over it.
      vec3 crease = mix( tint / max( tintWeight, 1.0 ), uInk, uCrease );
      float hole = ( 1.0 - centre ) * ( 1.0 - isOpen ) * step( 0.5, tintWeight )
        * ( 1.0 - sealHalo );

      // How much shadow is going into this pixel.  It is one number for
      // both the line and the skirt because the two are the same shadow at
      // two radii, and because it has to be the same number that decides
      // the coverage below.
      float ink = max( ring * uLine, shade * uSkirt );

      // The character itself is written out opaque.  A partly covered
      // pixel would show the page through it, and on the white body that
      // is the difference between a surface and a stain.
      //
      // The shadow outside it is *not* written out opaque, and this is the
      // whole difference between a shadow and a line.  The canvas is
      // composited over the page, so a pixel that carries the shadow's
      // colour at full coverage paints that colour solid -- which is ink,
      // whatever colour it is, and a one-pixel ink border round a white
      // figure on a white page is a sticker.  Carrying it at the same
      // fraction it was mixed at lets the page through underneath, and
      // what is left is a shadow lying on the page.
      float alpha = max( max( step( 0.5, base.a ), hole ), ink );
      vec3 rgb = mix( base.rgb, uInk, ink );
      rgb = mix( rgb, crease, hole );
      gl_FragColor = vec4( rgb, alpha );
    }
  `,
}

// Mouth shapes while speaking. Without a phoneme tracker the previous build
// simply scaled one mesh, which read as rubber. Cycling real viseme morphs
// gives the mouth distinct vowel silhouettes instead of one stretched oval.
const VISEMES = ['aa', 'ih', 'ou', 'ee'] as const
let visemeIndex = 0
let visemeClock = 0
let mouthEnvelope = 0

/** When the next authored gesture is due. */
let oneShotNextAt = 0
/** The authored gesture currently playing, if any. */
let oneShotPlaying = ''

function actionNameForStatus(status: YXZStatus) {
  if (status === 'processing' || status === 'thinking')
    return 'YXZ_Thinking'
  if (status === 'listening')
    return 'YXZ_Listening'
  if (status === 'success')
    return 'YXZ_Success'
  // Speaking keeps the body on the quiet idle pose: the mouth is the actor
  // while talking.  The authored speaking clip moves the head and jaw on
  // bones the auto-generated skin weights are weakest around, which reads
  // as distortion on the lower-left jaw; the idle pose is gentle, and the
  // viseme morphs carry the speech on top of it.
  if (status === 'speaking')
    return 'YXZ_Idle'
  return 'YXZ_Idle'
}

function selectAction(status: YXZStatus) {
  if (!mixer || actionMap.size === 0)
    return
  // A state clip always wins over an authored gesture: if the character
  // starts speaking halfway through a wave, the wave is where it stops.
  oneShotPlaying = ''
  const next = actionMap.get(actionNameForStatus(status)) ?? actionMap.get('YXZ_Idle')
  if (!next)
    return
  if (next === activeAction) {
    // Re-entering a one-shot should replay it instead of parking on its
    // clamped final frame.
    if (next.loop === THREE.LoopOnce && next.paused)
      next.reset().play()
    return
  }
  // The cross-fade is how a change of state reaches the body, and it has
  // to be long enough to read as a movement.  A fifth of a second was
  // quick enough for the small clips and far too quick for the ones that
  // change the arms: the thinking gesture brings the hand up to the chin
  // through forty degrees, and at a fifth of a second that is a snap
  // rather than a gesture.  Half a second is about what a person takes
  // to shift an arm, and it costs nothing when the two poses are close.
  const FADE = 0.5
  activeAction?.fadeOut(FADE)
  const oneShot = status === 'success'
  next.setLoop(oneShot ? THREE.LoopOnce : THREE.LoopRepeat, oneShot ? 1 : Infinity)
  next.clampWhenFinished = oneShot
  next.reset().fadeIn(FADE).play()
  activeAction = next
}

// ---------------------------------------------------------------------
// The authored one-shots.
//
// The gestures the behaviour layer improvises are small ones: a lean, a
// nod, a shift of weight.  They are the punctuation of a standing
// figure, not its vocabulary.
//
// The larger movements -- a wave, a greeting -- are not improvised at
// all.  They are authored, once, as clips inside the model file, and
// they are played the way a film is played: it starts, it runs to its
// end, it stops, and the character goes back to whatever it was doing.
// The only thing decided at runtime is which one, and when.
//
// This is the whole difference between a figure and a puppet.  A
// puppet's arms are moved by the same code that moves its breathing,
// and the eye can tell, because a hand that is halfway through a wave
// is a hand that has stopped moving.
const ONE_SHOT_CLIPS = [
  'YXZ_Wave',
]

function playOneShot(name: string) {
  if (!mixer)
    return
  const action = actionMap.get(name)
  if (!action)
    return
  activeAction?.fadeOut(0.25)
  action.setLoop(THREE.LoopOnce, 1)
  action.clampWhenFinished = false
  action.reset().fadeIn(0.3).play()
  activeAction = action
  oneShotPlaying = name
}

// When an authored gesture is due.
//
// Only while the character is standing and waiting.  A gesture that
// cuts across a sentence reads as a stumble, and one that fires while
// she is thinking reads as the thinking being interrupted.
function updateOneShots(time: number) {
  if (!mixer || actionMap.size === 0)
    return
  const status = props.status
  if (status !== 'idle' && status !== 'listening') {
    oneShotNextAt = time + 5 + Math.random() ** 1.5 * 9
    return
  }
  if (oneShotPlaying)
    return
  if (activeAction && activeAction.loop === THREE.LoopOnce) {
    oneShotNextAt = time + 3
    return
  }
  if (time < oneShotNextAt)
    return
  const pick = ONE_SHOT_CLIPS[Math.floor(Math.random() * ONE_SHOT_CLIPS.length)]
  if (!pick || !actionMap.has(pick)) {
    oneShotNextAt = time + 15
    return
  }
  playOneShot(pick)
  // Long enough that the gesture is not something the viewer waits for,
  // and long enough that it does not become the beat the scene is on.
  oneShotNextAt = time + 26 + Math.random() ** 1.4 * 46
}

function emotionForStatus(status: YXZStatus) {
  if (status === 'success' || status === 'speaking')
    return 'happy'
  if (status === 'processing' || status === 'thinking')
    return 'think'
  // Listening should read as warm attention, not wide-eyed surprise: a soft
  // smile with slightly narrowed eyes keeps the visitor engaged instead of
  // making the character look startled by what they are saying.
  if (status === 'listening')
    return 'happy'
  return 'relaxed'
}

function resize() {
  if (!renderer || !camera || !canvasContainer.value)
    return
  const width = Math.max(1, canvasContainer.value.clientWidth)
  const height = Math.max(1, canvasContainer.value.clientHeight)
  camera.aspect = width / height
  // Keep the whole silhouette inside narrow embeds as well as desktop stages.
  const halfFov = THREE.MathUtils.degToRad(camera.fov * 0.5)
  camera.position.z = Math.max(8.8, baselineWorldSize.x * 0.65 / (Math.tan(halfFov) * camera.aspect))
  camera.lookAt(0, 2.05, 0)
  camera.updateProjectionMatrix()
  renderer.setSize(width, height, false)
  // `composer.setSize` forwards to every pass, which is what keeps the edge
  // kernel the same physical size as the canvas instead of stretching with it.
  composer?.setSize(width, height)
  // The outline works in device pixels, so its texel size and its width both
  // have to follow the pixel ratio.  Otherwise the line would be twice as
  // thin on a retina screen as on a desktop one.
  const pixelRatio = renderer.getPixelRatio()
  if (outlinePass) {
    outlinePass.uniforms.uTexel.value.set(1 / (width * pixelRatio), 1 / (height * pixelRatio))
    outlinePass.uniforms.uRadius.value = OUTLINE_WIDTH * pixelRatio
    // The gap in the shell is a feature of the model, so it is the same
    // size on the screen whatever the screen's density is.  These two are
    // read in device pixels, so they have to follow the pixel ratio with
    // everything else.
    outlinePass.uniforms.uReach.value = OUTLINE_REACH * pixelRatio
    outlinePass.uniforms.uFill.value = OUTLINE_FILL * pixelRatio
    outlinePass.uniforms.uSeal.value = OUTLINE_SEAL * pixelRatio
  }
}

// Adds to a material's own shader patch rather than replacing it.
//
// MToon compiles itself through `onBeforeCompile`, so anything the stage
// wants to add to a MToon shader has to go after the library's patch has
// run, and the altered source has to be part of the program's cache key
// or three will hand the material a program compiled from the source it
// did not patch.  `key` is the caller's name for the patch, and it is what
// tells two patched programs apart.
function patchMtoonShader(
  material: THREE.Material,
  key: string,
  transform: (source: string) => string,
) {
  const target = material as THREE.Material & {
    onBeforeCompile?: (shader: { fragmentShader: string }, renderer: unknown) => void
    customProgramCacheKey?: () => string
  }
  // A patch may only be applied once to a material.
  //
  // The eye's shadow is one material on two meshes -- a left and a right
  // -- and the walk over the model visits both.  Patching the material
  // twice wrapped the patch round itself, and the second copy declared
  // the same two variables the first one had declared, so the shader
  // did not compile and the material was drawn with a broken program.
  // The grade is a piece of source, not a setting, so putting it in
  // twice is not a no-op; it is a syntax error.
  const applied = (target.userData.yxzShaderPatches ??= [] as string[])
  if (applied.includes(key))
    return
  applied.push(key)
  const compile = target.onBeforeCompile?.bind(target)
  const cacheKey = target.customProgramCacheKey?.bind(target)
  target.onBeforeCompile = (shader, renderer) => {
    compile?.(shader, renderer)
    shader.fragmentShader = transform(shader.fragmentShader)
  }
  target.customProgramCacheKey = () => `${cacheKey?.() ?? ''}|${key}`
  material.needsUpdate = true
}

// Replaces the last statement of a fragment shader that writes the colour.
// MToon ends with one, and it is the one whose output reaches the buffer,
// so it is the only safe place to change what a pixel finally is.
function replaceFinalColour(source: string, replacement: string) {
  const mark = 'gl_FragColor = vec4( col, diffuseColor.a );'
  const at = source.lastIndexOf(mark)
  if (at < 0)
    return source
  return `${source.slice(0, at)}${replacement}${source.slice(at + mark.length)}`
}

function prepareModel(model: THREE.Object3D) {
  model.traverse((object) => {
    if (!(object instanceof THREE.Mesh))
      return
    // The eye and mouth are separate meshes that live inside the helmet.
    // They have to stay out of the shadow map, and the reason is MToon
    // itself: a shaded pixel has its colour replaced by the flat shade
    // colour, so a recessed iris that the helmet shadows loses its blue
    // and turns into a pale grey disc.  The character then reads as awake
    // but lifeless.  The overlays take the scene lights like the rest of
    // the face and simply ignore the shadow map.
    const isFaceOverlay = object.name.startsWith('YXZ_')
    object.castShadow = !isFaceOverlay
    // The character does not receive its own shadow.
    //
    // The shell is one layer of surface, and a one layer shell cannot
    // shadow itself without the shadow map aliasing: the visor is a
    // curved panel lying almost edge on to the key light, so the depth
    // of the surface changes faster from one shadow texel to the next
    // than the texel can hold, and the panel ends up stippled with the
    // shadow map's own grid.  More bias does not fix it -- the bias
    // that removes the stipple detaches the shadow from the surface it
    // belongs to -- and neither does a bigger map, because the problem
    // is the angle and not the resolution.
    //
    // The form is not lost with it.  MToon's cel ramp carries the shape
    // on its own, and the ground keeps the shadow the character casts
    // on it, so the figure is still standing on something.
    object.receiveShadow = false

    // The halo is built as an object of its own so that it can carry a
    // light: the VRM gives it a cyan base colour and a cyan emission, and
    // the emission is what turns a ring of geometry into a ring of light.
    // The strength in the file is deliberately low -- the file is the
    // model's, and the model's colour should not depend on the stage's
    // exposure -- so the stage raises it here, where the stage's exposure
    // is known.
    const material = object.material
    for (const entry of Array.isArray(material) ? material : [material]) {
      if (!entry)
        continue
      // The shell is a single layer of surface, and where the scan tore,
      // there is a gap in it.  Culled, a gap shows the inside of the
      // character's own head -- a dark hole with a torn edge round it --
      // and a whole crown of those read as a shattered helmet rather than
      // as a helmet.  Drawing both sides puts the inner wall of the
      // shell back behind the gap, where the light can reach it, so a tear
      // reads as a soft shadow inside the model instead of a hole through
      // it.  MToon turns the normal round for a back face, so the inside
      // of the shell is lit like the outside rather than staying black.
      //
      // The shadow side is left alone on purpose: with both sides drawn,
      // the shadow map would be written by the back of every surface as
      // well, and a shell one layer thick would shadow itself.
      entry.side = THREE.DoubleSide
      if ('shadowSide' in entry)
        entry.shadowSide = THREE.FrontSide
      // The halo is a ring of light, and light has a colour.
      //
      // Its own texture is already the cyan of the visor trim, and the
      // ring is the only thing on the character that is lit by its own
      // colour rather than by the scene, so the emission is what decides
      // what the halo looks like.  Pushed to 2.6 it was three times over
      // white in every channel before the tone mapper ever saw it, and
      // the tone mapper does what tone mappers do with a value that far
      // over white: it desaturates it.  The ring came out flat white, on
      // a page that is nearly white, so the only part of it the eye
      // could find was the ink the outline pass drew round its edge --
      // a white hoop with a thin outline is a wire hoop, which is the one
      // thing a halo must not look like.
      //
      // At 1.35 the brightest blue is just over the bloom threshold and
      // the red channel is a third of the blue, so the ring stays a
      // saturated cyan, spills a little light round itself, and reads as
      // a ring of light rather than a ring of plastic.
      //
      // The lit colour is nearly black on purpose.  The halo is the one
      // thing on the character that is lit by its own colour rather than
      // by the scene, and a scene light on top of the emission washes
      // the band out to a pale grey-teal -- which, on a pale page, is
      // exactly the white hoop this started as.
      // The halo is the ring and its star together, because both of them
      // need the same two patches and splitting them across two branches
      // is how one of them ends up not patched at all.
      if (entry.name === 'YXZ_Halo' || entry.name === 'YXZ_HaloStar') {
        entry.emissiveIntensity = 1.25
        entry.emissive?.setRGB(0.10, 0.55, 0.85)
        const halo = entry.uniforms
        if (halo?.litFactor)
          halo.litFactor.value.setRGB(0.02, 0.10, 0.16)
        // The halo's own pixels, marked for the outline pass.
        //
        // Two things happen here and both have to happen inside the
        // material, because neither can be done from outside it.
        //
        // The first is the mark.  The outline pass finds the character's
        // silhouette by reading the alpha the beauty pass wrote, and the
        // halo is in that buffer, so it finds the halo's edge and draws
        // the line round it.  The line is the whole problem: light has no
        // outline, and a ring of light with a contour round it is a hoop
        // of wire.  Alpha is the only channel the outline pass reads, so
        // the halo writes a fixed value there -- half covered, which no
        // surface ever writes -- and the pass is taught to leave those
        // pixels out of the silhouette.
        //
        // The second is the gradient.  A flat ribbon lit by one flat
        // emission is one flat colour, and one flat colour across a band
        // is what makes light look like a painted plastic hoop.  What
        // makes the same band read as light is that it is brightest
        // along its middle and falls away towards both edges, which is
        // what the reference's halo does and what a rounded section of
        // light does.  The ribbon already carries the coordinate that
        // runs across its width, so the emission is shaped by it and the
        // geometry is left alone.
        //
        // The floor is high on purpose.  It used to be a fifth of the
        // middle, which put the edges of the ribbon at a twentieth of
        // the emission and made the ring a flat plate with a dark rim
        // round it, and a dark rim is a wire.  A ring of light dims
        // towards its edges; it does not go out.
        patchMtoonShader(entry, 'yxz-halo', (source) => {
          const add = 'col += totalEmissiveRadiance;'
          const at = source.indexOf(add)
          if (at >= 0) {
            source = `${source.slice(0, at)}float haloBand = sin( clamp( uv.y, 0.0, 1.0 ) * 3.14159265 );
  totalEmissiveRadiance *= 0.62 + 0.78 * haloBand;
  ${add}${source.slice(at + add.length)}`
          }
          // The last write of the fragment colour is the one the buffer
          // keeps, and it is the one that has to carry the mark.
          return replaceFinalColour(source, 'gl_FragColor = vec4( col, 0.5 );')
        })
      }
      // The eyes are the design's own lights: a pale oval that glows
      // from inside a dark visor, with no pupil in it at all.  They are
      // lit by their own emission, and the strength is what decides
      // whether they read as eyes or as two bright stickers.
      else if (entry.name === 'YXZ_EyeGlow') {
        entry.emissiveIntensity = 1.05
      }
      else if (entry.name === 'YXZ_EyeCore') {
        entry.emissiveIntensity = 1.55
      }
      // The mouth plate and the shadow behind the eyes are painted with
      // the body's own atlas, and they sit on the body rather than being
      // the body.  They still have to be graded like it, because a
      // material with a different rim, a different shade tone and a
      // different ramp shades differently -- and a patch of the face
      // that shades differently is a patch of the face you can see.  The
      // mouth plate in particular is the face, lifted a third of a
      // millimetre off it, and the whole point of it is that you cannot
      // tell it is there.
      else if (entry.name.startsWith('tripo_')
        || entry.name === 'YXZ_MouthPlate'
        || entry.name === 'YXZ_EyeShadow') {
        // The shell is what reads as plastic, and it is two numbers doing
        // it.  MToon's rim term is
        // `rimColor * pow(saturate(1 - dot(view, normal) + lift), power)`:
        // the rim colour in the file is near-white and the shell is
        // near-white, so every grazing surface -- which on a body this
        // rounded is most of the silhouette -- adds white on top of white
        // and clips.  A clipped rim is a highlight with no shape to it,
        // which is the glass look.
        //
        // The lift was the other half of it, and the lift is worse than
        // the colour.  It sits inside the `saturate`, so it does not
        // merely spread the rim back over the surface: it makes the rim
        // reach full strength while the surface is still turned *towards*
        // the camera, and it saturates the term outright on anything
        // turned away from it.  A face that is a few degrees past grazing
        // then gets the whole rim colour added on top of its own paint.
        //
        // That is not a highlight.  It is what turned the torn edge of
        // the visor into a comb of white whiskers standing over the dark
        // screen, which read as shattered glass rather than as a helmet
        // with a rim on it -- a dark navy texel came out as a pale one.
        // With no lift the rim is a true fresnel: nothing at all across
        // the face, full only at the edge itself.  Cooler, weaker and
        // tighter than it was, it stays a light along the edge instead of
        // a coat over the whole body.
        const uniforms = entry.uniforms
        if (uniforms?.parametricRimColorFactor)
          uniforms.parametricRimColorFactor.value.setRGB(0.22, 0.28, 0.40)
        if (uniforms?.rimLightingMixFactor)
          uniforms.rimLightingMixFactor.value = 0.06
        if (uniforms?.parametricRimFresnelPowerFactor)
          uniforms.parametricRimFresnelPowerFactor.value = 3.6
        // No lift at all.  A rim with no lift is a rim that only exists on
        // the last pixel or two before the silhouette, and on this model
        // that is exactly what is wanted: the shell keeps its shape from
        // the key light and the shade colour, and the rim only marks
        // where the form turns away.
        if (uniforms?.parametricRimLiftFactor)
          uniforms.parametricRimLiftFactor.value = 0
        // The other half is the shadow side.  `shadeColorFactor` only
        // darkens the unlit side to about three quarters of the lit side,
        // so there is almost no depth in the cel ramp and the body is one
        // flat white shape that the rim then sits on.  A cooler, deeper
        // shade gives the form something to be read against, and on a
        // character this white it is the difference between a painted
        // figure and a white blob: at three quarters the visor and the
        // blue panels sink into the body and the whole thing reads as a
        // chalky model of the design rather than the design itself.
        //
        // `shadingToonyFactor` is the width of the ramp between the lit
        // tone and the shade tone, and it is the one number that decides
        // whether the shell reads as a moulded surface or as a toy.
        //
        // MToon's gradient is `linearstep(-1 + toony, 1 - toony, dotNL)`,
        // so a *low* value spreads the ramp across most of the surface.
        // At 0.42 the light fades into the shade over about a hundred and
        // ten degrees and the terminator is a gradient rather than an
        // edge, which is what the reference's helmet does: the turn from
        // the lit top-left into the shaded lower-right is a long soft
        // fall, and the only crisp edge anywhere on the shell is the
        // painted one in the texture.  The VRM 1.0 default is 0.9, and
        // at 0.9 the ramp is a few degrees wide -- the helmet becomes a
        // lit shape, a shade shape and one clean line between them, the
        // form is carried entirely by that line, and that is the hard
        // shiny edge a plastic toy has and a rendered figure does not.
        //
        // It used to sit at 0.9 here with the paragraph above explaining
        // why it should not, which is the same plastic look with a
        // comment claiming it was not that.
        //
        // The wings are the constraint on how deep the shade may go.
        // They are near-horizontal sheets either side of the torso, so
        // the key rakes along them and they never reach the lit side at
        // all: at a shade of a third they come out a flat grey, and grey
        // wings on a white character read as unfinished rather than
        // shaded.  The shape is carried by the key light rather than by
        // the ramp, and the extra frontal fill is what keeps the wings
        // off that floor.
        if (uniforms?.shadeColorFactor)
          uniforms.shadeColorFactor.value.setRGB(0.33, 0.40, 0.62)
        if (uniforms?.shadingToonyFactor)
          uniforms.shadingToonyFactor.value = 0.42
        // And then the two things a toon shader cannot do for itself.
        //
        // The first is a highlight.  MToon has no specular lobe and no
        // environment term, so on a shell this white and this rounded the
        // only thing that varies across a panel is the cel ramp, and a
        // moulded surface with no highlight on it is a paper cut-out.
        // The reference's helmet has one broad soft brightening across its
        // upper left, which is the studio light the whole render was shot
        // with and is most of what makes it read as a finished surface.
        //
        // It is added in view space against a fixed direction rather than
        // against a real light, because a real light would need a specular
        // lobe to be worth anything and MToon has none.  It is scaled by
        // the surface's own colour, so it lands on the white shell and
        // leaves the dark visor alone -- a highlight that ignored the
        // albedo would be a haze over the whole character, and a haze is
        // the glass look all over again.
        //
        // The second is saturation.
        //
        // MToon has no environment term, so everything on the shell is
        // the texture's own colour multiplied by the scene's lights, and
        // a near-white shell under a strong white key lands very close to
        // the top of the tone curve, where the curve compresses and takes
        // the colour out of everything else with it.  That is why the
        // blue on this character kept reading as pale steel while the
        // reference shows a blue that is unmistakably blue: the blue is
        // in the texture, and the stage was taking it out again.
        //
        // Pushing away from the pixel's own luminance puts it back.  It
        // costs the whites nothing -- a white pixel has no saturation to
        // push -- and it is applied after the lighting so it grades what
        // the stage actually produced rather than what the file was
        // painted with.
        patchMtoonShader(entry, 'yxz-grade', source =>
          replaceFinalColour(
            source,
            `float yxzSheen = pow( saturate( dot( normalize( normal ), normalize( vec3( -0.42, 0.72, 0.55 ) ) ) ), 3.0 );
  col += material.diffuseColor * vec3( 1.0, 1.02, 1.08 ) * yxzSheen * 0.15;
  float yxzLuma = dot( col, vec3( 0.2126, 0.7152, 0.0722 ) );
  col = mix( vec3( yxzLuma ), col, 1.42 );
  gl_FragColor = vec4( col, diffuseColor.a );`,
          ))
      }
    }
  })
}

function fitActor(model: THREE.Object3D) {
  if (!actor)
    return
  const bounds = new THREE.Box3().setFromObject(model)
  const size = bounds.getSize(new THREE.Vector3())
  const center = bounds.getCenter(new THREE.Vector3())
  // Keep the character visually prominent while leaving enough floor margin
  // for the exhibition toolbar.
  const scale = 3.6 / Math.max(size.y, 0.001)
  actor.scale.setScalar(scale)
  // Offset the model inside the scaled actor so it stands centred on the
  // origin with a small floor margin above the bottom toolbar.
  model.position.set(-center.x, 0.32 / scale - bounds.min.y, -center.z)
  baselineWorldSize.copy(size).multiplyScalar(scale)
  // The actor's world matrix is what the renderer and the sanity check read,
  // and it is not recomputed until the next render pass.  Refresh it here so
  // the very first frame is already measured in the right place.
  actor.updateMatrixWorld(true)
}

function guardModelShape(seconds: number) {
  if (!vrm || !animatedModel || baselineWorldSize.y <= 0 || seconds - lastBoundsCheckAt < 0.24)
    return
  lastBoundsCheckAt = seconds
  // A skinned mesh does not change its bounding box when a bone rotates --
  // the box comes from the bind pose -- so measuring the bounds says
  // nothing about the pose.  What can actually go wrong is a bone driven
  // to a non-finite transform or flung far outside the body, and that is
  // what this checks.
  const humanoid = vrm.humanoid
  if (!humanoid)
    return
  const origin = animatedModel.getWorldPosition(new THREE.Vector3())
  const limit = baselineWorldSize.y * 3
  const probe = new THREE.Vector3()
  let fault = ''
  // The rig's own bones, by the names the runtime actually uses.
  //
  // `wing.L` and `wing.R` are the names in the file, but three.js
  // sanitises node names on load -- `PropertyBinding.sanitizeNodeName`
  // strips the dot -- so the bones arrive in the scene as `wingL` and
  // `wingR`.  A name written the way it is in the file matches nothing,
  // and a bone that matches nothing is a bone that nothing governs.
  const names = [...Object.keys(humanoid.humanBones ?? {}), 'halo', 'wingL', 'wingR']
  for (const name of names) {
    // The list mixes humanoid bones with the rig's own extras, so the name
    // cannot be narrowed to a humanoid bone name at compile time.
    const node = humanoid.getRawBoneNode(name as Parameters<typeof humanoid.getRawBoneNode>[0])
      ?? animatedModel.getObjectByName(name)
    if (!node)
      continue
    node.getWorldPosition(probe)
    if (!Number.isFinite(probe.x) || !Number.isFinite(probe.y) || !Number.isFinite(probe.z)) {
      fault = `${name} 变换出现非有限值`
      break
    }
    if (probe.distanceTo(origin) > limit) {
      fault = `${name} 被甩出模型范围`
      break
    }
  }
  if (!fault || motionGuardTriggered)
    return
  motionGuardTriggered = true
  console.warn('宜小智动作形体保护已触发，已回退到安全待机动作', { fault })
  activeAction?.stop()
  const safeAction = actionMap.get('YXZ_Idle')
  if (safeAction) {
    safeAction.reset().setLoop(THREE.LoopRepeat, Infinity).play()
    activeAction = safeAction
  }
}

// ---------------------------------------------------------------------
// The living layer.
//
// Every clip that ships with the model is built the same way: a handful
// of sines on one period, one period per clip.  That is the right way to
// author a walk cycle and the wrong way to author a person standing
// still.  On the head the idle clip runs three of those sines, one per
// axis, so the head traces a closed three-axis curve for as long as the
// page is open -- and a closed curve is exactly the "it is just rocking
// its head" reading, because the eye learns the shape after one loop and
// then waits for it to come round again.
// The fix is not a different set of sines.  A different set of sines is
// the same problem on a longer fuse: the eye is remarkably good at
// finding the period of a repetitive motion, and the only motion it
// cannot find the period of is motion that never repeats.
//
// So the motion is rebuilt in four layers, and the clip is only allowed
// to keep the one thing a clip is genuinely good at -- the shape of a
// breath and the shape of a weight shift.
//
//   1. the clip, with the visible loop taken out of the head
//   2. a slow wander, on a rate no two bones share
//   3. a postural bias, a random walk that settles into a new posture
//      and stays there for a while
//   4. occasional gestures, chosen at random and sometimes chained
//
// The result is a figure that is never in the same pose twice and is
// never in a hurry, which is what the reference does.
//
// Pulling a clip's keys towards the pose a bone holds on average is what
// takes the loop out.  Averaging the keys is the right average to pull
// towards, because the clip writes absolute local rotations: the mean
// keeps whatever constant offset the key was authored with (the thinking
// clip's raised arm, the listening clip's forward lean) and removes only
// the part that swings around it.  A factor of one leaves the clip
// alone; a factor of zero pins the bone to the pose it spends most of
// its time in.
function calmClipMotion(clip: THREE.AnimationClip, keep: Record<string, number>) {
  const suffix = '.quaternion'
  const mean = new THREE.Quaternion()
  const key = new THREE.Quaternion()
  const out = new THREE.Quaternion()
  let touched = 0
  for (const track of clip.tracks) {
    if (!(track instanceof THREE.QuaternionKeyframeTrack) || !track.name.endsWith(suffix))
      continue
    const factor = keep[track.name.slice(0, -suffix.length)]
    if (factor === undefined)
      continue
    const values = track.values
    // A track whose values are interleaved cannot be rewritten in place;
    // leaving it alone is better than corrupting it.
    if (!(values instanceof Float32Array))
      continue
    let x = 0
    let y = 0
    let z = 0
    let w = 0
    // A quaternion track stores four components per key.
    const keys = Math.floor(values.length / 4)
    // Quaternions are double covered: q and -q are the same rotation, and
    // an exporter is free to write either.  The exporter wrote half of
    // the neck bone's keys with the sign flipped, and a plain sum of
    // those cancels towards zero -- and a zero quaternion normalised is
    // the identity, which is not a pose any bone was ever in.  The head
    // hangs off the neck, so the head ends up somewhere it was never
    // drawn and the helmet opens up.  Chaining the keys into a single
    // hemisphere before summing is what makes the average mean anything.
    let previousX = 0
    let previousY = 0
    let previousZ = 0
    let previousW = 1
    for (let index = 0; index < keys; index++) {
      const at = index * 4
      let qx = values[at]
      let qy = values[at + 1]
      let qz = values[at + 2]
      let qw = values[at + 3]
      if (qx * previousX + qy * previousY + qz * previousZ + qw * previousW < 0) {
        qx = -qx
        qy = -qy
        qz = -qz
        qw = -qw
      }
      previousX = qx
      previousY = qy
      previousZ = qz
      previousW = qw
      x += qx
      y += qy
      z += qz
      w += qw
    }
    mean.set(x, y, z, w).normalize()
    for (let index = 0; index < keys; index++) {
      const at = index * 4
      key.set(values[at], values[at + 1], values[at + 2], values[at + 3])
      out.slerpQuaternions(mean, key, factor)
      values[at] = out.x
      values[at + 1] = out.y
      values[at + 2] = out.z
      values[at + 3] = out.w
    }
    touched++
  }
  return touched
}

// The bones this clip never moves.
//
// The mixer only rewrites a property when the track it holds has something
// new to say.  A bone whose rotation keys are all the same value is left
// exactly as it was, so if something else has written to it since the last
// frame, that write sticks and the next one lands on top of it.  The living
// layer writes every frame, so on such a bone it would accumulate without
// bound and walk the character out of its own rig -- a hundred degrees of
// drift inside ten seconds.
//
// Those bones are named here and skipped.  Nothing is lost by skipping them:
// the clip holds them still, so the living layer was the only thing that
// would have moved them, and a bone the animation does not touch is a bone
// with nothing to animate.
function constantRotationBones(clip: THREE.AnimationClip) {
  const still = new Set<string>()
  for (const track of clip.tracks) {
    if (!(track instanceof THREE.QuaternionKeyframeTrack) || !track.name.endsWith('.quaternion'))
      continue
    const values = track.values
    if (!(values instanceof Float32Array))
      continue
    let constant = true
    for (let at = 4; at < values.length && constant; at += 4) {
      if (values[at] !== values[0]
        || values[at + 1] !== values[1]
        || values[at + 2] !== values[2]
        || values[at + 3] !== values[3]) {
        constant = false
      }
    }
    if (constant)
      still.add(track.name.slice(0, -'.quaternion'.length))
  }
  return still
}

// How much of each clip survives.
//
// The idle clip is the one that is on screen for most of the session, and
// the head is what the eye watches, so the idle head is cut back to almost
// nothing and the movement is handed to the layers below, which do not
// repeat.  The breath stays: it is in the chest, it is slow, and a
// character that is not breathing is a mannequin.
//
// The other clips keep more of their shape because they are short and they
// are carrying a meaning -- the listening clip's nod and the thinking
// clip's hand under the chin are the point of those states, and flattening
// them would leave the state unreadable.  What is taken out of them is the
// wobble around the pose, not the pose.
//
// The legs are the exception that applies to every state, and the reason
// is the same in all of them.  The reference character -- the airi girl --
// moves her legs four and a half degrees and her hips a degree and a
// half, and that shift is the largest single movement in her whole idle.
// It is what makes a standing figure read as a person rather than as a
// prop, and it belongs to the legs where it belongs.
//
// They used to keep seven tenths of the clip's own leg motion, which was a
// small rocking of the hips on the clip's eight second period.  Seven
// tenths of it was not enough to read as a weight shift and plenty enough
// to read as a metronome -- and, worse, it left the legs as the one part
// of the figure the living layer could not touch.  There was then nowhere
// else for the life to go but the head, and the head wobbling is what
// came of it.
const CALM_LEGS = {
  leftUpperLeg: 0,
  rightUpperLeg: 0,
  leftLowerLeg: 0,
  rightLowerLeg: 0,
  leftFoot: 0,
  rightFoot: 0,
}

// ---------------------------------------------------------------------
// The authored idle.
//
// This is the whole point of the model, and it is the reason the
// upstream character reads as a person rather than as a prop.
//
// The upstream project ships one authored idle for its own character:
// a single coherent movement for the whole figure -- a weight shift
// through the hips, the same shift carried up the spine, the arms riding
// the shoulders, the head riding the neck.  One movement, one figure.
//
// What this model had instead was a noise layer per bone: eighteen
// bones, each with its own drift, its own tremor, its own posture
// signal, its own breath share.  Every one of them was small, and
// together they read as a figure that never held still -- restless
// rather than alive, and broken rather than moving, because no two
// bones were ever reading the same thing at the same time.
//
// So the body stops being built out of noise and is built out of that
// one movement instead.  The idle is retargeted onto this rig (see
// `composables/vrm/authored-idle.ts`), the state clips give up the
// bones it drives, and the behaviour layer is left with the head, the
// wings and the ring -- the parts that are hers rather than the
// skeleton's.
//
// The arms are not in the list.  The thinking gesture and the wave are
// gestures of the arms, and they are worth more than two degrees of
// idle swing; the arms hang off the shoulders, so they still travel
// with the body instead of standing beside it.
const AUTHORED_BONES = [
  'hips',
  'spine',
  'chest',
  'upperChest',
  'neck',
  'leftShoulder',
  'rightShoulder',
  'leftUpperLeg',
  'leftLowerLeg',
  'leftFoot',
  'leftToes',
  'rightUpperLeg',
  'rightLowerLeg',
  'rightFoot',
  'rightToes',
]

/**
 * Take the bones the clips must not touch out of a clip.
 *
 * Two clips writing the same bone is not a blend: three's mixer
 * averages the two values, so a wave and an idle would come out as a
 * smear halfway between the two poses.  The idle keeps the body and the
 * clip keeps what it is for.
 *
 * Two sets of bones come out of every clip.
 *
 * The first is the skeleton, which the authored idle owns: the idle's
 * clock runs on through every state change, so the weight shift the
 * character is standing in never jumps when she starts speaking.
 *
 * The second is the character's own -- the wings and the ring.  Those
 * are not the skeleton's and they are not the clip's either: each clip
 * in the file holds them at its *own* constant, and the constants are
 * up to sixteen degrees apart.  So the wings were held in one pose while
 * idle and in another while speaking, and every state change snapped
 * them across.  Before that they were not held at all -- the clips
 * still had seven degrees of their own wing motion in them -- so they
 * flapped on their own clock, on top of a body that was barely moving,
 * which is the loudest single thing a figure like this can do wrong.
 *
 * The behaviour layer owns them instead, and it holds them the same way
 * in every state.
 */
const BEHAVIOUR_BONES = ['wingL', 'wingR', 'halo']

function releaseAuthoredBones(clip: THREE.AnimationClip) {
  const owned = new Set([...AUTHORED_BONES, ...BEHAVIOUR_BONES])
  clip.tracks = clip.tracks.filter((track) => {
    const dot = track.name.lastIndexOf('.')
    if (dot < 0)
      return true
    return !owned.has(track.name.slice(0, dot))
  })
}

const CLIP_CALM: Record<string, Record<string, number>> = {
  YXZ_Idle: {
    // Zero, not small.
    //
    // The head is most of this character's silhouette, so whatever the clip
    // leaves in it is what the viewer reads as the character being restless.
    // And "less" does not fix it: at 6% of the clip's head curve it is still
    // the same closed eight-second ellipse, just a smaller one -- a wobble
    // too small to read as a decision and too regular to read as a person,
    // which is the exact definition of a tic.  So the head is taken out of
    // the loop entirely and handed to the behaviour layer below, which can
    // hold it perfectly still for ten seconds and then turn it somewhere
    // specific.
    head: 0,
    neck: 0,
    // The torso carries the loop, and because the head sits on top of it
    // every degree here is a degree of head.  Measured on the shipped clip,
    // a third of the sway still put the head through nearly four degrees of
    // closed eight-second oval -- an amount the eye reads as rocking, not as
    // breathing.  These are cut to the point where the residual oval is under
    // one degree, at which point it stops being something to watch and the
    // breath layer below becomes the only thing moving the chest.
    // Zero rather than small, for the whole spine.
    //
    // A tenth of the clip's sway is under a degree and nobody would miss it,
    // but it is not free: the mixer rewrites these bones every frame and the
    // living layer multiplies into them every frame, and where a bone's
    // animated pose sits near a half turn the two interleave badly enough to
    // show as an occasional one-frame snap.  Taking the track out entirely
    // leaves the mixer writing once and the living layer assigning outright,
    // which is the same arrangement the head already uses and cannot go
    // wrong.  Nothing is lost but the sway, which was not wanted.
    upperChest: 0,
    chest: 0,
    spine: 0,
    hips: 0,
    leftUpperArm: 0,
    rightUpperArm: 0,
    leftLowerArm: 0,
    rightLowerArm: 0,
    leftHand: 0,
    rightHand: 0,
    ...CALM_LEGS,
  },
  YXZ_Listening: {
    // This is the state the viewer actually sits and watches in, and it was
    // the worst offender: a little over half of the clip's head curve left,
    // the head never came to rest for a single second of a ninety-second run.
    // The nod that made listening readable is now a decision the behaviour
    // layer takes a few times a minute instead of a loop it never leaves.
    head: 0,
    neck: 0,
    upperChest: 0,
    chest: 0,
    spine: 0,
    hips: 0,
    leftUpperArm: 0,
    rightUpperArm: 0,
    leftLowerArm: 0,
    rightLowerArm: 0,
    leftHand: 0,
    rightHand: 0,
    ...CALM_LEGS,
  },
  YXZ_Thinking: {
    // The head goes with everything else.  The chin gesture is the forearm
    // and the hand; the head only has to be looking down at it, and the
    // attention model already holds it down and to one side for a long time
    // in this state, which says "thinking about it" far better than a loop
    // of the head swinging over the hand.
    head: 0,
    neck: 0,
    upperChest: 0,
    chest: 0,
    spine: 0.16,
    hips: 0,
    leftUpperArm: 0,
    // Zero rather than most of it.  The hand under the chin is carried by
    // the forearm and the fingers, which the living layer never touches, so
    // the gesture survives; the shoulder no longer carries a loop of its own
    // that the living layer would then be fighting every frame.
    rightUpperArm: 0,
    rightLowerArm: 0.78,
    rightHand: 0.78,
    ...CALM_LEGS,
  },
  YXZ_Speaking: {
    // The mouth is doing the acting here.  A head that moves continuously
    // underneath a moving mouth gives the eye two things to follow and it
    // ends up following neither, so the body holds and only the face works.
    head: 0,
    neck: 0,
    upperChest: 0,
    chest: 0,
    spine: 0,
    hips: 0,
    leftUpperArm: 0,
    rightUpperArm: 0,
    leftLowerArm: 0,
    rightLowerArm: 0,
    leftHand: 0,
    rightHand: 0,
    ...CALM_LEGS,
  },
  YXZ_Success: {
    // Loud, but not a loop.  The celebration gets its energy from the wing
    // flick and the lean the behaviour layer reaches for, which are two
    // seconds of movement rather than eight seconds of swaying.
    head: 0,
    neck: 0,
    upperChest: 0,
    chest: 0,
    spine: 0,
    hips: 0,
    leftUpperArm: 0,
    rightUpperArm: 0,
    leftLowerArm: 0,
    rightLowerArm: 0,
    leftHand: 0,
    rightHand: 0,
    ...CALM_LEGS,
  },
}

/**
 * The arms of the standing states.
 *
 * Every clip in the file was drawn with its own curve for the arms, and
 * the curves have different shapes, so the constant each one settles on
 * is up to eight degrees away from the others.  The arms are held rather
 * than animated, so a difference between two held poses is a difference
 * the viewer sees as the arms moving when nothing has happened -- and
 * the arms are the second thing the eye goes to after the face.
 *
 * So the standing states are given the same arms.  The two states whose
 * arms mean something -- the thinking gesture and the wave -- keep their
 * own, because those are movements and movements are what they are for.
 */
const SHARED_ARM_BONES = [
  'leftUpperArm',
  'rightUpperArm',
  'leftLowerArm',
  'rightLowerArm',
  'leftHand',
  'rightHand',
]

const SHARED_ARM_CLIPS = ['YXZ_Listening', 'YXZ_Speaking', 'YXZ_Success']

function shareHeldPose(clips: THREE.AnimationClip[]) {
  const reference = clips.find(clip => clip.name === 'YXZ_Idle')
  if (!reference)
    return
  for (const clip of clips) {
    if (!SHARED_ARM_CLIPS.includes(clip.name))
      continue
    for (const bone of SHARED_ARM_BONES) {
      const from = reference.tracks.find(track => track.name === `${bone}.quaternion`)
      const to = clip.tracks.find(track => track.name === `${bone}.quaternion`)
      if (!from || !to)
        continue
      const values = to.values
      for (let at = 0; at < values.length; at += 4) {
        values[at] = from.values[0]
        values[at + 1] = from.values[1]
        values[at + 2] = from.values[2]
        values[at + 3] = from.values[3]
      }
    }
  }
}

// The bones the living layer moves.
//
// The head is deliberately the quietest.  On a chibi the head is most of
// the silhouette, so anything the head does is read as attention, and
// attention that never settles reads as a tic.  The torso carries more of
// the movement than the head does, which is also how a person standing
// and thinking actually distributes it: the shoulders move, the head only
// follows now and then.
//
// `rate` is the bone's own base frequency and no two bones share one, so
// the body never arrives at a configuration it has been in before.  The
// periods run from about fourteen seconds on the halo to about fifty on
// the head: a figure that changes its posture every few seconds looks
// fidgety, and one that never changes looks dead.
const LIFE_BONES: {
  bone: string
  drift: number
  /**
   * How much of the signal this bone takes.
   *
   * For a bone that is driven by the walk this is its share of the
   * walk, in the head's own units: the hips take a little under half
   * of what the head takes, the shoulders a fifth, and the neck and
   * the head the rest.  For a bone that keeps its own noise it is
   * how much of that noise reaches it.
   */
  gain: number
  micro: number
  breath: number
  lag: number
  follow?: number
  /**
   * How much of the head's own slow movement this bone takes.
   *
   * This is the share that makes the figure one piece.  The head has a
   * slow drift of its own -- the rock -- and the body used to have a
   * different slow drift of its own, and the two had no relationship to
   * each other at all.  The result on screen was a head that moved over
   * a body that stood there, which is the single oldest way to make a
   * figure read as a puppet with a face on it.
   *
   * So the body takes a share of the head's movement.  The head does
   * not know it has done this, and does not need to: the body is
   * carrying the head's motion, and what is left over -- the head's
   * own excess over its share -- is what still reads as the head being
   * the head.
   */
  lead?: number
  rate: number
  phase: number
  /**
   * What moves this bone.
   *
   * `body`  the figure's own walk -- the lean that goes through the
   *         hips, the spine, the chest and the shoulders.
   * `neck`  the head's own walk, a beat late, so that the neck comes
   *         through underneath the head's movement.
   * `head`  the head's own walk, and the small movements on top.
   * `noise` the bone's own noise, which is what the wings, the arms
   *         and the ring keep.
   *
   * The chain from the hips to the shoulders used to be `noise`, like
   * everything else, and that was the last of the circling.  Five
   * bones each reading their own stretch of noise, stacked one on
   * another, is five unrelated drifts on the head's pitch and five
   * more on its tilt -- and the head's silhouette is the sum of all of
   * them.  A sum of ten unrelated drifts draws a closed curve, and a
   * closed curve is what the eye cannot stop watching.
   *
   * They read one walk now, and the head reads one walk of its own,
   * and the two are the same shape.  The head's silhouette is a line
   * again, and the line is not a line drawn by a machine: it is a
   * figure leaning, and the small movements are what make it a
   * person.
   */
  drive: 'body' | 'neck' | 'head' | 'noise'
  /**
   * The length of the noise this bone reads its posture from.
   *
   * Every bone used to read the *same* noise, and the lag between them was
   * the only thing that made them different.  That is a travelling wave: the
   * hips lead, the spine answers a third of a second later, the chest a
   * little after that, and the head arrives last.  Measured, the whole chain
   * peaked at a single 4.3 second period with an autocorrelation of 0.84 --
   * the same rhythm, in phase, in every bone of the torso.  A figure whose
   * chest, shoulders and head all rock on one beat is a figure on a swing,
   * and because the head inherits all of it, the head's silhouette describes
   * a closed curve in space.  That curve is what reads as circling.
   *
   * So each bone now reads its own stretch of the noise, at a length that
   * is not a multiple of any other's.  The bones are no longer copies of one
   * signal with a delay on them; they are five unrelated drifts that happen
   * to be on the same figure, and the sum of five unrelated drifts wanders
   * without ever closing.
   */
  cell: number
}[] = [
  // The bones the behaviour layer still owns.
  //
  // The list used to run to eighteen: the hips, the spine, the chest,
  // the upper chest, the neck, both arms, the wings, the ring, and both
  // legs from the thigh down.  Every one of them read a signal of its
  // own -- a drift, a tremor, a posture sample, a share of the breath --
  // and no two of them ever read the same signal at the same time.
  //
  // That is what the figure looked like: eighteen small movements that
  // agreed with each other about nothing.  The body was busy and the
  // figure was not alive, because a figure is alive when its parts move
  // *together*, and eighteen independent parts do not move together no
  // matter how small each of them is.
  //
  // The skeleton is not in this list any more.  It is driven by the
  // authored idle -- one movement, retargeted onto this rig -- and the
  // behaviour layer adds nothing to it.  What is left here is the head,
  // which is aimed rather than animated, the two arms, which hold their
  // pose and ride the shoulders, and the wings and the ring, which are
  // the character's own and not the skeleton's.
  //
  // The head keeps nothing at all.
  //
  // Everything the head does has to be a decision or a shape, or it
  // reads as a tic.  The only things that may move this bone are the
  // walk, the attention model, and the small movements -- all three of
  // which are further down, and none of which is a drift.
  { bone: 'head', drift: 0, gain: 0, micro: 0.02, breath: 0, lag: 0.46, rate: 0.019, phase: 6.5, cell: 22.7, follow: 0, drive: 'head' },
  // The arms and the wings ride on the shoulders, so they take the
  // shoulder rise and very little of their own.  They used to take a
  // seventh of a degree each on top of the chest's third, which put
  // nearly half a degree of the same five second nod into them.
  // The arms are held, not animated.
  //
  // They used to take a share of their own noise, which meant that each
  // arm was drifting on a signal of its own while the shoulders it is
  // attached to were drifting on another.  Two signals on one limb is
  // what a twist looks like from the outside: the hand ends up
  // somewhere the shoulder never sent it.
  //
  // So the arms take nothing.  What they do is ride the shoulders,
  // which they get for free -- they hang off the upper chest, so they
  // already carry the whole body's movement.  A raised arm that moves
  // with the chest and does nothing else is a raised arm; an arm with
  // its own drift is a broken joint.
  { bone: 'leftUpperArm', drift: 0, gain: 0, micro: 0, breath: 0, lag: 0.26, rate: 0.047, phase: 7.8, cell: 12.7, follow: 0, drive: 'noise' },
  { bone: 'rightUpperArm', drift: 0, gain: 0, micro: 0, breath: 0, lag: 0.26, rate: 0.051, phase: 9.1, cell: 15.7, follow: 0, drive: 'noise' },
  { bone: 'wingL', drift: 0.12, gain: 0.34, micro: 0.02, breath: 0.02, lag: 0.34, rate: 0.059, phase: 10.4, cell: 10.9, follow: 0, lead: 0.05, drive: 'noise' },
  { bone: 'wingR', drift: 0.12, gain: 0.34, micro: 0.02, breath: 0.02, lag: 0.34, rate: 0.063, phase: 11.7, cell: 14.3, follow: 0, lead: 0.05, drive: 'noise' },
  // The ring carries almost nothing and takes an age to get anywhere: a
  // degree and a bit of wander on a quarter-minute period.  Enough that it
  // is not a decal stuck to the model, far short of a spin -- a halo that
  // visibly turns is the single most mechanical thing a character like
  // this can do.
  //
  // It used to wander four times as far as this.  A ring that drifts is a
  // ring the eye can watch going round, and the ring is the largest single
  // shape on screen, so a drift on it reads as the whole character
  // circling rather than as the halo settling.
  { bone: 'halo', drift: 0.12, gain: 0.10, micro: 0.03, breath: 0.04, lag: 0.44, rate: 0.038, phase: 13.0, cell: 21.1, follow: 0, lead: 0.12, drive: 'noise' },
]

// The weight shift, and who takes how much of it.
//
// The reference character -- the airi girl -- stands with her weight on
// one leg, shifts it, and stands on the other, and the shift is the
// largest single movement in her whole idle.  Measured on her clip,
// her two thighs roll through four degrees and a half *together*, with
// the difference between them barely moving, her feet counter-rotate so
// that they stay flat on the ground, and her hips yaw a degree.
//
// That last part is the important one.  Her hips do not rock: they
// turn.  And the head, which hangs off all of it, rides the same
// movement rather than making one of its own.
//
// This model had none of it.  The head had its own wander, on its own
// noise, and the body had nothing, so the two disagreed with each
// other -- the body stood still while the head swung about inside it,
// and a head that moves against a still body reads as a tic no matter
// how small the movement is.
//
// So the signal lives here, the legs are given back to the living
// layer to be driven from it, and the head's own wander is cut back to
// a texture it cannot see.  What is left moving is one movement.
const WEIGHT_SWAY: Record<string, { roll: number, yaw: number, pitch: number }> = {
  // The hips turn rather than roll.
  //
  // The reference's root moves far more in yaw than in roll -- a
  // degree of roll against three quarters of a degree of yaw -- and
  // the turn is the part that carries: it is what a figure does when
  // it puts its weight down on one leg.  The roll is not here
  // because the walk gives it to the hips already, in the same
  // proportion it gives it to the shoulders, and a second roll on
  // top of that would put the head's silhouette back on a curve.
  //
  // The turn itself is not here either: the hips read the reference's
  // root directly now, so that the body turns by the same amount she
  // does and the head, which is solved for, answers back.
  hips: { roll: 0, yaw: 0, pitch: 0 },
  // The thighs swing over.  Both of them, the same way, which is what
  // the reference does: the body goes over the feet rather than the
  // weight going from one foot to the other.
  leftUpperLeg: { roll: 2.30, yaw: 0, pitch: 0 },
  rightUpperLeg: { roll: 2.30, yaw: 0, pitch: 0 },
  // The knees give a little of it back, which is the softness in a
  // standing leg.
  leftLowerLeg: { roll: -1.30, yaw: 0, pitch: 0 },
  rightLowerLeg: { roll: -1.30, yaw: 0, pitch: 0 },
  // And the feet take the rest of it, so that they stay flat on the
  // ground.  A foot that tilts is a foot the figure is standing on one
  // edge of, and it reads as a mistake however small it is.
  leftFoot: { roll: -1.30, yaw: 0, pitch: 0 },
  rightFoot: { roll: -1.30, yaw: 0, pitch: 0 },
  // The ring leans a little with the figure.
  //
  // It is held in its own frame, so it does not follow the body the way
  // the rest of the figure does, and a ring that does not move at all
  // while the body leans under it reads as a sticker.  A third of the
  // body's lean is enough to tie the two together and far short of
  // enough to look like the ring is being carried around.
  halo: { roll: 0.40, yaw: 0, pitch: 0 },
}

// ---------------------------------------------------------------------
// The vocabulary of a figure standing still.
//
// What makes a standing character look casual is not that it moves more --
// it is that the moves are *discrete* and the space between them is
// long.  A person at a counter is still for four seconds, glances
// sideways at something, holds it for a second, comes back, and is still
// again.  A character that is always in motion is not casual, it is
// busy, and the eye stops reading the motion and starts waiting for the
// next one.
//
// So every entry here is one finished movement with a beginning and an
// end, sized to be readable rather than continuous, and the scheduler
// below leaves long gaps between them.  The head is in here a lot, and
// that is the point: it was taken out of the clip precisely so that the
// only thing moving the head is a decision.
//
// The angles are smaller than they look like they should be.  A glance
// at seventeen degrees on a head this size is a look across the room, and
// doing that every ten seconds is a character who cannot settle; at nine
// it is a glance.  The whole difference between relaxed and restless is
// whether the eye can follow the head back.
interface LifeActionChannel {
  bone: string
  axis: 0 | 1 | 2
  deg: number
  /** -1 / 1 to pick a side, 0 to follow the movement's own side */
  side?: -1 | 0 | 1
}

interface LifeAction {
  kind: string
  channels: LifeActionChannel[]
  /** total length of the movement, in seconds */
  dur: number
  /** fraction of it spent winding up the other way first */
  lead: number
  /** fraction of it spent holding the result */
  hold: number
  /** how far the eyes travel with it, as a multiple of the head turn */
  gaze: number
  weight: number
}

const LIFE_ACTIONS: LifeAction[] = [
  // Everything below moves the body.  The head is not in this list and is
  // not meant to be: it is aimed by the attention model further down, which
  // holds where it points instead of returning to centre.  A body gesture
  // is right to come back to where it started -- a shrug does -- but a head
  // that comes back to where it started every few seconds is a metronome,
  // and a metronome is what the eye recognises as fake before it has any
  // opinion about the rest.
  //
  // The few entries below that do name the head name it on one axis only.
  // A head that tilts *and* lifts in the same movement traces an arc, and
  // a body that leans *and* turns at the same time puts the head on that
  // arc as well -- and a head that keeps arriving at new points along a
  // curve is a head circling.  The head's own three axes belong to the
  // attention model, one per trip, and nothing else may spend them.
  //
  // The head does not need its own channel to be carried by a lean, either:
  // it hangs off the neck, which hangs off the upper chest, so a lean of
  // the chest already carries it.  Naming it as well only doubled the
  // angle and made the lean read as a swerve.
  // Weight onto one leg: the whole torso goes, the head goes with it.
  //
  // Every angle in this list is smaller than it used to be, and every
  // movement is longer, and both of those changes were made for the
  // same reason.
  //
  // A movement is written as a set of bones, and each bone's angle adds
  // to the ones below it, so a movement that leans the spine two and a
  // half degrees and the chest two and the neck one and a half and the
  // head two and a half moves the head by eight and a half degrees.  It
  // sounds like a lean.  It is not: eight and a half degrees of head,
  // covered in the third of a second, is the figure lurching, and the
  // reference character -- who is the standard this is measured against
  // -- never moves her head more than eight degrees a second at all.
  //
  // So the movements are now about half the size and about a third
  // longer, and the head's own life above them does the rest of the
  // work.  A movement is an accent on top of a figure that is already
  // alive; it is not the only thing that moves.
  //
  // Nothing below moves an arm.  That is a change, and it is the whole
  // of what was wrong with the previous version.
  //
  // The arm bones on this rig do not point where a person would expect:
  // they run diagonally out of the shoulder pads, and the left one is
  // already raised in the sculpt.  A rotation written about a world
  // axis and carried into one of those bones is therefore carried
  // through a frame that is already turned, so a movement that was
  // meant to be a shoulder settling reads on screen as the upper arm
  // winding around its own shoulder -- and two arms doing that at
  // slightly different times reads as the whole figure coming apart.
  // The eyes read that as broken long before they read it as broken.
  //
  // The large movements that want an arm -- a wave, a greeting -- are
  // not improvised here either.  They are authored, once, as clips in
  // the model file, and they are played the way a film is played: it
  // starts, it runs to its end, it stops.  A gesture that has to be
  // re-invented every frame is a gesture that can come out halfway,
  // and halfway through a wave is a wave that looks broken.
  // A small nod to nobody.  Kept short and kept rare; a nod that happens
  // every few seconds is a tic, and a nod that happens every half minute
  // is a person.
  {
    kind: 'nod',
    channels: [
      { bone: 'head', axis: 0, deg: 1.4 },
    ],
    dur: 2.2,
    lead: 0.16,
    hold: 0.08,
    gaze: 0.2,
    weight: 0.45,
  },
  {
    kind: 'wingFlick',
    channels: [
      { bone: 'wingL', axis: 1, deg: 2.6 },
      { bone: 'wingR', axis: 1, deg: -2.3 },
    ],
    dur: 2.0,
    lead: 0.14,
    hold: 0.08,
    gaze: 0,
    weight: 0.6,
  },
  {
    kind: 'haloSettle',
    channels: [
      { bone: 'halo', axis: 2, deg: 1.0 },
      { bone: 'halo', axis: 1, deg: 0.7 },
    ],
    dur: 3.4,
    lead: 0.24,
    hold: 0.3,
    gaze: 0,
    weight: 0.6,
  },
  // A small deliberate tilt of the head.
  //
  // The head's three axes belong to the attention model, which holds
  // where it points rather than sweeping back to the middle -- and a
  // head that comes back to the middle every few seconds is a
  // metronome.  This one is different in the way that matters: it is
  // rare, it is small, and it does not come back to the middle, it
  // comes back to where it was, which is a correction rather than a
  // look.  A tilt that holds for a moment and then straightens up is
  // one of the most human things a standing figure does.
  {
    kind: 'headTilt',
    channels: [
      { bone: 'head', axis: 2, deg: 0.9 },
      // The nod under the tilt.
      //
      // A tilt on its own is a degree of roll with no pitch anywhere
      // near it, and one of those every half minute is enough to pull
      // the head's two channels apart again -- which is the one thing
      // this whole layer is trying to stop.  The reference's head
      // never separates them, and a nod under the tilt is what she
      // does instead.
      { bone: 'head', axis: 0, deg: 0.45 },
    ],
    dur: 3.0,
    lead: 0.2,
    hold: 0.26,
    gaze: 0.1,
    weight: 0.5,
  },
]

// Which movements suit which state.
//
// The character does not stand the same way while it is thinking as it
// does while it is waiting, and it is not the same figure on screen
// either way -- a thinking face that only ever looks straight ahead reads
// as a render with a status label on it.  Unlisted movements keep their
// own weight.
const LIFE_ACTION_BIAS: Record<YXZStatus, Record<string, number>> = {
  idle: {
    haloSettle: 1.2,
    nod: 0.3,
    headTilt: 0.55,
    wingFlick: 0.5,
  },
  listening: {
    nod: 2.4,
    headTilt: 0.8,
    wingFlick: 0.4,
  },
  thinking: {
    headTilt: 0.6,
    haloSettle: 0.9,
    nod: 0.25,
  },
  processing: {
    wingFlick: 1.6,
    haloSettle: 0.8,
    headTilt: 0.5,
    nod: 0.6,
  },
  speaking: {
    nod: 1.9,
    haloSettle: 0.8,
    headTilt: 0.5,
    wingFlick: 0.6,
  },
  success: {
    wingFlick: 2,
    headTilt: 0.5,
    haloSettle: 0.9,
    nod: 0.6,
  },
}

// How much of the living layer each state gets.
//
// Speaking is the quietest: the clip already carries a movement for every
// phrase, and the mouth is doing the acting there, so anything else moving
// at the same time is noise.  The celebration is quiet for the same reason
// from the other side -- the clip is already the loudest thing on screen.
const LIFE_STATE_WEIGHT: Record<YXZStatus, number> = {
  idle: 1,
  listening: 0.85,
  thinking: 0.72,
  processing: 0.72,
  speaking: 0.28,
  success: 0.55,
}

// How far the head is allowed to travel from straight ahead in each state.
// This is separate from the body weight above because the two answer to
// different things: the body weight is about how much fidgeting a state
// permits, and this is about how much of the room the character is
// attending to.  Speaking barely moves the head because the mouth is busy.
const ATTENTION_GAIN: Record<YXZStatus, number> = {
  idle: 1,
  listening: 0.92,
  thinking: 0.95,
  processing: 0.9,
  speaking: 0.3,
  success: 0.85,
}

// ---------------------------------------------------------------------
// The noise every movement here is built out of.
//
// So the sway is a smooth signal now -- but smooth is not the same as
// alive, and the version that shipped was smooth in the way a swinging
// weight is smooth.  Four sine waves, none of them a multiple of
// another, and the sum still has a period: the eye finds the fastest
// one, locks onto it, and from then on the head is a metronome with a
// face.  Measured, the head was busy eighty-eight percent of the time
// and it was rolling two degrees of tilt every few seconds, which on a
// head this large is not a lean -- it is a swing.
//
// What is wanted is not less motion.  It is motion that has no period.
//
// So the idle is built out of noise now.  A value noise is a random
// value at every whole number of some unit, joined to its neighbour by
// a quintic curve -- quintic rather than cubic because the second
// derivative stays continuous, so the joins leave no corner for the eye
// to catch.  Three octaves at three different lengths give the signal
// structure at three scales at once, and none of the three is a period.
// Nothing in it ever comes back to the same value, so there is nothing
// for the viewer to learn.
//
// The seed is drawn afresh each session, so the character stands
// differently every time the page is opened, and the slowest octave is
// subtracted from the fast ones, so the pose wanders around where it
// started instead of walking off across the room over a minute.
const MOTION_SEED = Math.random() * 997

function motionHash(n: number, seed: number) {
  const s = Math.sin(n * 127.1 + seed * 311.7) * 43758.5453123
  return s - Math.floor(s)
}

function motionNoise(x: number, seed: number) {
  const i = Math.floor(x)
  const f = x - i
  const u = f * f * f * (f * (f * 6 - 15) + 10)
  const a = motionHash(i, seed) * 2 - 1
  const b = motionHash(i + 1, seed) * 2 - 1
  return a + (b - a) * u
}

function motionFbm(x: number, seed: number) {
  return motionNoise(x, seed) * 0.58
    + motionNoise(x * 1.79 + 17.3, seed + 5.7) * 0.27
    + motionNoise(x * 2.61 + 41.9, seed + 11.3) * 0.15
}

// ---------------------------------------------------------------------
// Attention.
//
// This is the part the character was missing, and it is a different idea
// from an action.  An action is an excursion: it leaves, it comes back, and
// the pose either side of it is the same pose.  That is the right shape for
// a shrug or a shift of weight and the wrong shape for a head, because a
// head that returns to the same pose every few seconds crosses the middle
// of its range over and over, and a thing that crosses the middle of its
// range over and over is rocking -- which is exactly what a loop of glances
// looks like however good each individual glance is.
//
// What a person actually does is look somewhere and stay there.  They turn
// to the window, hold it while whatever they were looking at is still
// interesting, and only then drift off to something else.  The looking is
// most of it; the turning is a fraction of a second.  So the head here has
// a *target* rather than a gesture, and the gesture is only the trip.
//
// Three things follow, and they are what makes it read as casual:
//
//   dwell     The target is held for five to twenty seconds.  Long enough
//             that the character is somewhere for a while rather than
//             passing through.
//   inertia   The next target tends to be on the same side as the last one.
//             Two glances opposite in a row look like a metronome; two to
//             the same side look like someone who is still looking at the
//             thing they were looking at.
//   size      Most re-aims are a couple of degrees.  Occasionally it looks
//             right across the room and the turn is worth watching.  A
//             re-aim that is always large is a nervous character; one that
//             is never large is a camera on a tripod.
//
// The head's two big channels are not independent, and this is the
// number that says so.
//
// Everything that moves the head -- the walk, the small movements, the
// looks below, and the whole chain of the body it hangs off -- moves
// the tilt in proportion to the chin, and the proportion is the same
// everywhere.  That is what keeps the head on one line in the plane of
// its face.  Measured over two minutes, the reference's pitch and her
// tilt move together at 0.98, and this model used to be at 0.73,
// which is an ellipse, and an ellipse is a circle seen from the side.
// A circle is what the eye cannot stop watching, and it is the whole
// of the complaint about the head circling.
//
// The ratio is the reference's: her tilt spans ten degrees and a half
// against her chin's seven and a quarter.
const HEAD_ROCK_RATIO = 1.378
interface AttentionTarget {
  yaw: number
  pitch: number
  roll: number
}

// How far the head may travel from straight ahead.
//
// This was seventeen degrees of yaw, and seventeen degrees on a head this
// size is a look across the room.  Measured over a two-minute idle, the
// head's yaw swung with a standard deviation of seven degrees and it was
// in motion two thirds of the time -- which is not a character looking
// around, it is a character turning.
//
// Then it came down again, to six and a half, and it was still wrong, and
// the reason is the reference.  The airi girl's yaw channel is flat to
// within a degree over the whole two minutes: she never turns to look at
// anything.  Everything she does with her head is a rock and a tilt, and
// that is a completely different thing from looking around, and the eye
// reads them completely differently.
//
// So the ceiling here is three degrees of yaw, which is a glance and not
// a scan, and the head's living comes from the rock below instead.
//
// The pitch and the roll are not independent ceilings.  The tilt is
// given a larger one because the tilt follows the rock: every degree
// of rock carries a degree and a third of tilt with it, and the
// ceiling has to be wide enough to let that through, or the coupling
// is undone by the clamp and the head is back to two channels.
const ATTENTION_CEILING = { yaw: 0.38, pitch: 0.34, roll: 0.46 }

// Per state: how big a step is typical, how often the character comes back
// to the middle, and how much longer it settles somewhere while thinking
// about something.  Thinking is the state where a person stops scanning.
const ATTENTION_SHAPE: Record<YXZStatus, {
  scale: number
  recentre: number
  dwell: number
  pitchBias: number
  rest: number
}> = {
  idle: { scale: 1, recentre: 0.18, dwell: 1, pitchBias: -0.1, rest: -0.1 },
  listening: { scale: 0.72, recentre: 0.42, dwell: 0.85, pitchBias: -0.25, rest: -0.7 },
  thinking: { scale: 0.78, recentre: 0.16, dwell: 1.75, pitchBias: 1.5, rest: 2.3 },
  processing: { scale: 0.82, recentre: 0.3, dwell: 1.3, pitchBias: 0.9, rest: 1.4 },
  speaking: { scale: 0.62, recentre: 0.46, dwell: 0.8, pitchBias: -0.15, rest: -0.3 },
  success: { scale: 0.88, recentre: 0.3, dwell: 0.9, pitchBias: -0.2, rest: -0.5 },
}

const attention: AttentionTarget = { yaw: 0, pitch: 0, roll: 0 }
const attentionFrom: AttentionTarget = { yaw: 0, pitch: 0, roll: 0 }
const attentionTo: AttentionTarget = { yaw: 0, pitch: 0, roll: 0 }
// Where the head is right now, in the same degrees the rotation is written
// in.  The eyes aim off this, so the two agree by construction.
const attentionNow: AttentionTarget = { yaw: 0, pitch: 0, roll: 0 }
// While the character is holding a look, it is not frozen.
//
// A held pose with nothing at all in it reads as a paused render.  What a
// person does while they are looking at something is settle: the head
// drifts a degree, the chin comes up a fraction, and it settles again.
// The drift is slow, small, and it never changes what the character is
// looking at -- it only makes the hold feel like there is a person behind
// it.
// The settle inside a held look.
//
// A held pose with nothing at all in it reads as a paused render, so the
// head drifts a little while it holds.  It used to drift four tenths of a
// degree, on all three axes at once, which is enough to keep the pose
// from looking frozen and also enough to mean the head is never still.
// The drift is smaller now, and it is the only thing in the whole model
// that moves the head while the head is supposed to be holding a look.
const ATTENTION_DRIFT = 0.2
const attentionDriftSample = new THREE.Vector3()

function attentionDrift(time: number, out: THREE.Vector3) {
  out.set(
    motionFbm(time / 13.7 + 3.1, MOTION_SEED + 131.7) * ATTENTION_DRIFT,
    motionFbm(time / 15.1 + 7.7, MOTION_SEED + 151.3) * ATTENTION_DRIFT * 0.7,
    motionFbm(time / 17.3 + 5.3, MOTION_SEED + 171.1) * ATTENTION_DRIFT * 0.45,
  )
  return out
}

let attentionStart = -1
let attentionDur = 1
let attentionNextAt = 3.6
let attentionSide = 1

function clampAttention(target: AttentionTarget) {
  target.yaw = THREE.MathUtils.clamp(target.yaw, -ATTENTION_CEILING.yaw, ATTENTION_CEILING.yaw)
  target.pitch = THREE.MathUtils.clamp(target.pitch, -ATTENTION_CEILING.pitch, ATTENTION_CEILING.pitch)
  target.roll = THREE.MathUtils.clamp(target.roll, -ATTENTION_CEILING.roll, ATTENTION_CEILING.roll)
  return target
}

// Choosing the next thing to look at.
//
// The step is drawn from a curve rather than a range so that small re-aims
// are the common case and a look across the room is the exception.  The
// side is sticky, and the stickiness is what stops the alternation that
// reads as a metronome; the character only really turns about when it has
// drifted a long way from the middle, and the clamp on the ceiling is what
// forces that eventually.
function pickAttention(status: YXZStatus) {
  const shape = ATTENTION_SHAPE[status] ?? ATTENTION_SHAPE.idle
  // Sticky.  The stickiness is what stops the alternation that reads as a
  // metronome: two looks to the same side read as someone who is still
  // looking at the thing they were looking at, and only a look that has
  // drifted a long way from the middle earns a look the other way.
  if (Math.random() < 0.82)
    attentionSide = Math.random() < 0.5 ? -1 : 1
  // While it is holding somewhere, the character occasionally makes a tiny
  // correction instead of a real look.  Nobody sits perfectly still for
  // twenty seconds; they settle, drift a degree, and settle again.  Small
  // enough that it is never read as a movement on its own.
  //
  // One axis, like every other trip.  This used to nudge all three at
  // once by a random amount each, which is a walk in three dimensions
  // rather than a correction: repeated, it draws a wandering diagonal
  // line and the eye reads it as the head searching around for something
  // it cannot name.  A correction is a correction in one direction.
  if (Math.random() < 0.12) {
    const microScale = (0.15 + Math.random() * 0.35) * shape.scale
    const axis = Math.random()
    const nudged = { yaw: attention.yaw, pitch: attention.pitch, roll: attention.roll }
    const amount = (Math.random() * 2 - 1) * microScale
    // Mostly a correction in height, and hardly ever in yaw.  A correction
    // in yaw is the same movement as a real look, only smaller, and the
    // head cannot tell the two apart; a run of small yaws is a run of
    // small looks, and it is the small looks that make a head look like
    // it is searching for something.
    if (axis < 0.22) {
      nudged.yaw += amount
    }
    else if (axis < 0.82) {
      nudged.pitch += amount * 0.7
      // A correction in height takes a little tilt with it, the same
      // way the rock does.  One that moved the two axes separately is
      // a correction in two directions, and two directions is a shape.
      nudged.roll += amount * 0.7 * HEAD_ROCK_RATIO
    }
    else {
      nudged.roll += amount * 0.5
      nudged.pitch += amount * 0.5 / HEAD_ROCK_RATIO
    }
    clampAttention(nudged)
    attentionFrom.yaw = attentionNow.yaw
    attentionFrom.pitch = attentionNow.pitch
    attentionFrom.roll = attentionNow.roll
    attentionTo.yaw = nudged.yaw
    attentionTo.pitch = nudged.pitch
    attentionTo.roll = nudged.roll
    attentionDur = THREE.MathUtils.clamp(0.6 + Math.random() * 0.6, 0.6, 1.3)
    return
  }
  // Which axis this re-aim moves.
  //
  // One, and only one.  Two axes moving at once trace an arc, and an arc
  // is what reads as circling: the eye sums the two movements and sees a
  // curve, not a decision.  A head that turns while it also tips, and
  // turns again while it is still tipped, comes out as a figure turning
  // its head in slow circles -- which is exactly what this model used to
  // do, and exactly what the user kept seeing.
  //
  // So the three axes are given separate turns of their own.  And the
  // three are not equal: a look up or down is the commonest thing a
  // person does with their head while they are standing and thinking, a
  // turn to the side is the next, and a tilt is a treat, rare enough to be
  // worth having.  Turning to the side was the commonest of the three
  // here, and that is what a two-minute idle measured as a head that
  // spends two thirds of its time turning.
  //
  // The order is now the reference's order.  The reference character's
  // yaw channel is flat for the whole two minutes -- she never turns to
  // look at anything -- and the only thing her head does is rise and
  // fall and tilt.  A turn of the head is a bigger event than a look up
  // or down, and it is the one thing that reads as the character
  // searching for something, so it is the rarest of the three here
  // rather than the commonest.
  const pick = Math.random()
  const target = {
    yaw: attention.yaw,
    pitch: attention.pitch,
    roll: attention.roll,
  }
  if (pick < 0.15) {
    if (Math.random() < shape.recentre) {
      // Coming back to the middle is a movement in its own right, and it is
      // the one that happens on purpose: the character looks back at you.
      //
      // It lands *near* the middle rather than exactly on it, and that is
      // the difference between a character looking at you and a character
      // being returned to a position.  A head that comes back to the same
      // angle every time is a metronome, and a metronome is the one thing
      // the whole attention model exists to avoid.
      target.yaw = (Math.random() * 2 - 1) * 1.3 * shape.scale
    }
    else {
      // Aiming further out from where it already is, rather than replacing
      // the target outright, is what makes two glances in a row feel like
      // the same thought continuing.
      //
      // The step is how far the character turns from where it is looking
      // now, drawn from a curve so that most turns are a glance and one
      // in five is a look across the room.
      //
      // The pull is deliberately weak.  A strong one would keep the head
      // pinned near the middle and the character would sit there staring
      // straight ahead; a strong one is also what turns a sequence of
      // looks into a pendulum.  A weak one lets a single look travel a
      // real distance and lets the character drift back over the course
      // of the next few looks, which is what a person standing at a
      // counter does.
      const step = (0.4 + Math.random() ** 1.8 * 1.5) * shape.scale
      target.yaw = attention.yaw
        + attentionSide * step
        - Math.sign(attention.yaw) * Math.min(Math.abs(attention.yaw), 0.4 + Math.random() * 1)
    }
    // Pushed too far off for comfort, the character stops at the edge and
    // the next turn goes the other way.  A ceiling nobody ever reaches is
    // not a ceiling, but a ceiling that is reached by snapping back to the
    // middle is a jump, and a jump is worse than a limit.
    const limit = ATTENTION_CEILING.yaw - 1.5
    if (Math.abs(target.yaw) > limit) {
      target.yaw = Math.sign(target.yaw) * limit
      attentionSide = (target.yaw > 0 ? -1 : 1)
    }
  }
  else if (pick < 0.78) {
    // A look up or down, taken as a step from where the head already is.
    //
    // It used to be set against the state's resting height instead, which
    // meant every trip threw the head to a fresh height rather than moving
    // it from where it was: the head went up, then down, then up again,
    // each time crossing its own middle, and a head that crosses its middle
    // every few seconds is nodding.  A node every seven seconds, for two
    // minutes, is a character with a tick.
    //
    // So the look is a step, and the step is undone a little every time.
    // The head wanders around the height the state wants it at -- level
    // while idle, down while thinking -- and it never gets far from it,
    // because every trip gives back part of the last one.
    const down = Math.random() < 0.5 + shape.pitchBias * 0.5
    const step = (0.32 + Math.random() ** 1.7 * 1.35) * shape.scale
    const offset = attention.pitch - shape.rest
    target.pitch = attention.pitch + (down ? step : -step)
    // The pull back towards the height the state wants.
    //
    // It used to give back at most a degree and a bit of the last step,
    // and the step was worth up to three and a half, so the head's
    // height was a random walk with almost no restoring force.  It
    // settled somewhere and stayed there: measured, the head held a
    // three degree upward tilt for eighty seconds without once going
    // back to level.  A head that parks at an angle and stays parked is
    // not looking at anything, it is stuck.
    const pull = Math.min(Math.abs(offset), 0.5 + Math.random() * 1.1)
    target.pitch -= Math.sign(offset) * pull
    // The tilt comes with the rock.
    //
    // This is the change that stops the head circling.  The look up
    // or down used to be a trip on the pitch alone, and the tilt was
    // a trip of its own on another occasion, and two trips on two
    // axes that never happen together are what draw an ellipse in the
    // plane of the face -- and an ellipse is a circle seen from the
    // side.  The reference keeps her two channels locked together at
    // 0.98, which is what makes her head a rock and not a wheel.
    target.roll = attention.roll + (target.pitch - attention.pitch) * HEAD_ROCK_RATIO
  }
  else {
    // A tilt, also taken as a step, and also giving back part of the last
    // one.  A tilt that is set from scratch each time is a tilt that the
    // head arrives at from level every time, so the head crosses level
    // again and again; taken as a step, the head leans into a tilt, holds
    // it, and comes most of the way back out of it.
    const step = (0.22 + Math.random() ** 2 * 0.75) * shape.scale
    target.roll = attention.roll + (Math.random() < 0.5 ? -step : step)
    const pull = Math.min(Math.abs(target.roll), 0.4 + Math.random() * 0.8)
    target.roll -= Math.sign(target.roll) * pull
    // And a tilt takes a little of the rock with it, the other way
    // round, so that the two stay on the same line.
    target.pitch = attention.pitch + (target.roll - attention.roll) / HEAD_ROCK_RATIO
  }
  clampAttention(target)
  // The trip starts from the held pose, not from where the head happens to
  // be.  The wander is added on top of the trip rather than being left out
  // of it, so it never appears all at once when the trip lands.
  attentionFrom.yaw = attention.yaw
  attentionFrom.pitch = attention.pitch
  attentionFrom.roll = attention.roll
  attentionTo.yaw = target.yaw
  attentionTo.pitch = target.pitch
  attentionTo.roll = target.roll
  const distance = Math.hypot(
    attentionTo.yaw - attentionFrom.yaw,
    attentionTo.pitch - attentionFrom.pitch,
    (attentionTo.roll - attentionFrom.roll) * 0.6,
  )
  // A short trip takes a short time.  Scaling by distance is what stops a
  // one-degree correction from arriving as slowly as a look across the room
  // and reading as a drift.  The floor is deliberately higher than it looks
  // like it should be: a head that covers thirty degrees in half a second
  // is faster than a person turns, and the eye reads the difference as a
  // twitch rather than as looking.
  // The trip takes its own time.  A head that covers the same distance in
  // exactly the same number of seconds every time is on a schedule, and a
  // schedule is what the eye learns and then stops following.
  attentionDur = THREE.MathUtils.clamp(
    (1.7 + distance * 0.8) * (0.85 + Math.random() * 0.4),
    1.7,
    4.2,
  )
}

// The shape of the trip, which is the only part that is a gesture at all.
//
// It starts slightly the other way -- the wind-up, without which a turn is
// a servo -- leaves fast, arrives with a little more than it meant to,
// gives that back, and stops.  It does not go back to where it started.
// That last part is the whole point: the return that made the old
// movements read as rocking is simply absent here.
function attentionEnvelope(k: number) {
  if (k >= 1)
    return 1
  // Zero, not one, before the trip starts.  Returning the far value here
  // would put the head at its destination for the frame the transition
  // begins, which is a jump rather than a movement.
  if (k <= 0)
    return 0
  // The wind-up is small.
  //
  // It used to be thirteen percent of the step, which sounds like a
  // detail and is not: a head that pulls back a seventh of the way
  // before it turns is a head on a pendulum, and a pendulum that is set
  // going once every ten seconds reads as rocking.  Six percent is
  // enough to take the edge off the start of the movement and not enough
  // to be a movement of its own.
  const lead = 0.14
  const out = 0.8
  const hold = 0.07
  const a2 = lead + out
  const a3 = a2 + hold
  if (k < lead)
    return -0.05 * smoothstep(k / lead)
  if (k < a2) {
    const t = (k - lead) / out
    // The stroke used to be a two-and-a-quarter power ease-out, which is
    // at its very fastest in the first fifth of it.  On a head this size
    // that reads as the head being flicked rather than as the head
    // arriving somewhere, and the faster states flick it hardest.  The
    // quintic has no corner in it at either end, so the trip starts and
    // stops without a jolt.
    return -0.05 + 1.05 * (0.5 - 0.5 * Math.cos(Math.PI * t))
  }
  if (k < a3) {
    // Held a fraction past the target, giving back slowly.
    return 1 - 0.04 * ((k - a2) / hold)
  }
  // One small damped wobble on the way to rest, and then rest.  Under a
  // degree and gone in a quarter second, so it stops the arrival from
  // looking like a frame being held.
  const t = (k - a3) / (1 - a3)
  return 1 + 0.025 * Math.sin(Math.PI * 2 * t) * Math.exp(-4.5 * t) * (1 - t)
}

function updateAttention(time: number, status: YXZStatus) {
  if (attentionStart < 0) {
    attentionDrift(time, attentionDriftSample)
    attentionNow.yaw = attention.yaw + attentionDriftSample.x
    attentionNow.pitch = attention.pitch + attentionDriftSample.y
    attentionNow.roll = attention.roll + attentionDriftSample.z
    if (time < attentionNextAt)
      return
    pickAttention(status)
    attentionStart = time
    return
  }
  const k = (time - attentionStart) / attentionDur
  // The wander rides on top of the trip for the whole of it.
  //
  // It used to be dropped for the length of the trip and put back the
  // instant the trip landed, which is a quarter of a degree appearing in
  // one frame: the head did not move there, it jumped.  Measured, that
  // jump and the rock underneath it were taking the head past eleven
  // degrees a second, where the reference never goes past eight and a
  // quarter, and a head that jumps is a head that reads as broken.
  attentionDrift(time, attentionDriftSample)
  if (k >= 1) {
    attentionStart = -1
    attention.yaw = attentionTo.yaw
    attention.pitch = attentionTo.pitch
    attention.roll = attentionTo.roll
    attentionNow.yaw = attentionTo.yaw + attentionDriftSample.x
    attentionNow.pitch = attentionTo.pitch + attentionDriftSample.y
    attentionNow.roll = attentionTo.roll + attentionDriftSample.z
    const shape = ATTENTION_SHAPE[status] ?? ATTENTION_SHAPE.idle
    // The dwell.  Power-shaped, so most stays are a comfortable fifteen
    // seconds and the long ones turn up rarely enough to be worth having.
    //
    // It used to run from under three seconds to fourteen, and a look
    // that ends and another that begins three seconds later is a look
    // that is really a metronome with a hold in the middle of it.  The
    // space between the movements is most of what makes a figure read as
    // standing there rather than as working through a list.
    attentionNextAt = time + (3.2 + Math.random() ** 1.6 * 8.0) * shape.dwell
    return
  }
  const e = attentionEnvelope(k)
  attentionNow.yaw = THREE.MathUtils.lerp(attentionFrom.yaw, attentionTo.yaw, e) + attentionDriftSample.x
  attentionNow.pitch = THREE.MathUtils.lerp(attentionFrom.pitch, attentionTo.pitch, e) + attentionDriftSample.y
  attentionNow.roll = THREE.MathUtils.lerp(attentionFrom.roll, attentionTo.roll, e) + attentionDriftSample.z
}

// A slow wander, one axis at a time.
//
// This used to return a single number that the three axes then scaled by
// 1, 0.8 and 0.9.  Three scaled copies of one signal are not three signals:
// the axes stay locked in a fixed phase relationship, the rotation vector
// traces a closed curve in three dimensions, and the figure reads as turning
// its head in slow circles rather than shifting where it looks.
//
// So each axis gets its own.  Every frequency here is the bone's own rate
// times a product of irrationals -- sqrt2, sqrt3, sqrt5, the golden ratio --
// and no two of the twelve resulting frequencies share a common period.  A
// curve that never closes cannot be learned, which is the whole point.
const DRIFT_AXIS = [1, 1.6180339887, 1.4142135624]
const DRIFT_TERM = [1, 1.4142135624, 1.7320508076, 2.2360679775]
const DRIFT_WEIGHT = [0.46, 0.28, 0.16, 0.1]
const DRIFT_PHASE = [0, 2.3999632297, 4.1231056256]

function lifeDrift(time: number, rate: number, phase: number, axis: number) {
  const base = time * rate * DRIFT_AXIS[axis]
  const skew = phase * (1 + axis * 0.61) + DRIFT_PHASE[axis]
  return Math.sin(base + skew) * DRIFT_WEIGHT[0]
    + Math.sin(base * DRIFT_TERM[1] + skew * 1.7) * DRIFT_WEIGHT[1]
    + Math.sin(base * DRIFT_TERM[2] + skew * 2.3) * DRIFT_WEIGHT[2]
    + Math.sin(base * DRIFT_TERM[3] + skew * 3.1) * DRIFT_WEIGHT[3]
}

// A very small tremor, at a rate the eye reads as "alive" rather than
// "shaking".  It is there so that a pose is never exactly held: a figure
// frozen between two movements still looks like a render.
function lifeMicro(time: number, phase: number) {
  // Slow.  This used to run at 1.9 and 3.1 hertz, which at three hundredths
  // of a degree is invisible but not *inaudible*: the eye reads a high
  // frequency wobble as a vibration rather than as life, and a chibi head
  // is large enough that the vibration shows.  Periods of five and eight
  // seconds read as drift instead.
  return Math.sin(time * 0.83 + phase * 3.7) * 0.62
    + Math.sin(time * 1.31 + phase * 1.3) * 0.38
}

// The breath.
//
// Once the clip's own loop is taken out of the torso there has to be
// something left moving the chest, or the figure stops being a person
// standing and becomes a render being held still.  This is that something,
// and it is deliberately the one piece of motion that never stops.
//
// A breath is unlike every other movement here in that the eye *wants* to
// see it repeat: it is the metronome the stillness is measured against, and
// a chest that never rises reads as a doll no matter how good the glances
// are.  So it is periodic, and it is kept under a degree -- small enough
// that it never becomes something to watch, large enough to be caught at
// the edge of vision.
//
// It used to be four and a third seconds, which is a real rate for a
// person but an unlucky one here: the posture noise has an octave at
// four and a third seconds as well, so the breath and the drift beat
// against each other and the whole torso locked onto one rhythm that the
// eye could learn in ten seconds.  A longer breath, on its own period,
// beats against nothing.
//
// The shape is not a sine.  In and out are not the same length: the chest
// fills faster than it empties, which is what the second harmonic buys, and
// it is why the beat does not read as a pulse.  The period itself is walked
// by a slow drift, because a breath that lands on exactly 4.35 seconds for
// ten minutes is a machine.
const BREATH_BASE = 5.25

function lifeBreath(time: number) {
  const walk = time * (1 + 0.021 * Math.sin(time * 0.077) + 0.013 * Math.sin(time * 0.031 + 2.1))
  const u = (walk / BREATH_BASE) % 1
  const inhale = Math.sin(u * Math.PI * 2)
  const shape = Math.sin(u * Math.PI * 4 + 0.9)
  return inhale * 0.78 + shape * 0.22
}

const postureSample = new THREE.Vector3()

interface LifeBone {
  node: THREE.Bone
  cell: number
  // The bone's own world rotation in the rest pose.  A floating ring that
  // hangs off the upper chest has to be pinned to the orientation it was
  // designed at, and this is that orientation.
  restWorld: THREE.Quaternion
  // The parent's world rotation in the rest pose.  The extra motion is
  // authored in world axes -- a nod is a nod whether the character is
  // standing or leaning -- and then carried into the bone's own space
  // through this frame, so the motion rides on the pose instead of
  // fighting it.
  restParent: THREE.Quaternion
  restParentInv: THREE.Quaternion
  // Set when the active clip has had this bone taken away entirely.  The
  // mixer writes such a bone exactly once and then never touches it again,
  // so the extra motion has to be assigned from `base` rather than layered
  // onto whatever is currently there -- layered, it would accumulate and
  // walk the character out of its own rig within seconds.
  ownedBy: string
  base: THREE.Quaternion
  drift: number
  // How much of the signal this bone takes.  For a bone the walk
  // drives it is its share of the walk; for a bone that keeps its own
  // noise it is how much of that noise reaches it.
  gain: number
  // What moves this bone: the figure's walk, the head's walk, or the
  // bone's own noise.
  drive: 'body' | 'neck' | 'head' | 'noise'
  micro: number
  breath: number
  lag: number
  rate: number
  phase: number
  // How much of the head's turn the body goes with.  When a person turns
  // to look at something, the shoulders go with it by a fraction and a
  // beat later; without that the head turns on top of a torso that is
  // frozen, and the two do not agree about which way the character is
  // facing.
  follow: number
  // How much of the head's own slow movement this bone takes.  The head
  // and the body used to move on two unrelated signals, which put a
  // moving head on a standing body; this is the share that makes the
  // figure one piece.
  lead: number
  // How much of the weight shift this bone takes.
  //
  // The weight shift is one signal, and the whole figure is built out
  // of it: the legs swing over, the feet counter so that they stay on
  // the ground, the hips go with it and the spine answers a little
  // further up.  The numbers are the shape of a body standing with its
  // weight on one leg.
  sway: { roll: number, yaw: number, pitch: number }
}

let lifeBones: LifeBone[] = []
let lifeClock = 0
// The movement in progress, and the ones already shown this session.  The
// history is what makes the character feel like it has been standing there
// for a while rather than like it is working through a list.
interface LifeMove {
  action: LifeAction
  start: number
  side: number
}
let lifeMove: LifeMove | null = null
let lifeNextAt = 4.5
const lifeHistory: string[] = []
const lifeEuler = new THREE.Euler()
const lifeWorld = new THREE.Quaternion()
const lifeLocal = new THREE.Quaternion()
const lifeOffset = new THREE.Vector3()
const lifeParentWorld = new THREE.Quaternion()
// Where the head has to end up, as a world rotation.  The head's own
// bone is solved for against it.
const headShapeSample = new THREE.Quaternion()
const lifeHeadNode = { current: undefined as THREE.Object3D | undefined }
const lifeWorldPosition = new THREE.Vector3()
// Bone name -> its slot in `lifeBones`, so a movement can be written
// straight onto the bones it names instead of being matched by string on
// every bone on every frame.
const lifeBoneIndex = new Map<string, number>()
// Degrees of extra rotation, three per bone, refilled each frame from the
// movement in progress.
let lifeMoveDeg = new Float32Array(0)
// Where the movement in progress is sending the head, and how hard.
const lifeGazeTurn = new THREE.Vector2()
let lifeGazeStrength = 0

// Debug switches, so the two halves of the motion can be compared against
// each other without a rebuild: `?noCalm=1` leaves the clips as they were
// authored, `?noLife=1` leaves the character standing perfectly still.
let calmEnabled = true
let lifeEnabled = true

function readMotionFlags() {
  const params = new URLSearchParams(window.location.search)
  calmEnabled = !params.has('noCalm')
  lifeEnabled = !params.has('noLife')
}

function smoothstep(value: number) {
  const k = THREE.MathUtils.clamp(value, 0, 1)
  return k * k * (3 - 2 * k)
}

// The world rotation of a node, from the live local rotations up the
// chain.
//
// The world matrices are only rebuilt when the frame is drawn, so asking
// one for its world rotation here would read the pose from the frame
// before.  Walking the chain by hand is a handful of multiplications and
// it is always the pose as it is right now.
function chainWorldQuaternion(node: THREE.Object3D, out: THREE.Quaternion) {
  out.copy(node.quaternion)
  let parent = node.parent
  while (parent) {
    out.premultiply(parent.quaternion)
    parent = parent.parent
  }
  return out
}

// The same walk for position.
//
// The rotation has to be applied before the translation is added: a point
// local to this node is turned by this node's own rotation into its
// parent's space, and only then offset by the parent's position.  Adding
// the translation first and rotating the sum would swing every offset
// twice.
function chainWorldPosition(node: THREE.Object3D, out: THREE.Vector3) {
  out.set(0, 0, 0)
  let current: THREE.Object3D | null = node
  while (current) {
    out.applyQuaternion(current.quaternion)
    out.add(current.position)
    current = current.parent
  }
  return out
}

// Collects the bones the living layer is allowed to move.
//
// The bones are taken from the skeleton the mesh is actually skinned to,
// not by name from the scene.  three-vrm keeps a second, normalized rig
// whose nodes carry the same names as the raw ones, and a name lookup
// would find either of them; the skeleton is unambiguous.
function collectLifeBones(root: THREE.Object3D) {
  const skeletonBones = new Map<string, THREE.Bone>()
  const everyBone = new Map<string, THREE.Bone>()
  root.traverse((object) => {
    if (object instanceof THREE.SkinnedMesh) {
      for (const bone of object.skeleton?.bones ?? [])
        skeletonBones.set(bone.name, bone)
    }
  })
  root.traverse((object) => {
    if (object instanceof THREE.Bone && object.name)
      everyBone.set(object.name, object)
  })
  lifeBones = []
  lifeHeadNode.current = undefined
  lifeBoneIndex.clear()
  const restParent = new THREE.Quaternion()
  for (const item of LIFE_BONES) {
    const node = skeletonBones.get(item.bone) ?? everyBone.get(item.bone)
    if (!node?.parent)
      continue
    if (item.bone === 'head')
      lifeHeadNode.current = node
    node.parent.getWorldQuaternion(restParent)
    lifeBoneIndex.set(item.bone, lifeBones.length)
    lifeBones.push({
      node,
      restWorld: chainWorldQuaternion(node, new THREE.Quaternion()).clone(),
      restParent: restParent.clone(),
      restParentInv: restParent.clone().invert(),
      ownedBy: '',
      base: new THREE.Quaternion(),
      drift: item.drift,
      gain: item.gain,
      drive: item.drive,
      micro: item.micro,
      breath: item.breath,
      lag: item.lag,
      cell: item.cell,
      rate: item.rate,
      phase: item.phase,
      follow: item.follow ?? 0,
      lead: item.lead ?? 0,
      sway: WEIGHT_SWAY[item.bone] ?? { roll: 0, yaw: 0, pitch: 0 },
    })
  }
  lifeMoveDeg = new Float32Array(lifeBones.length * 3)
}

// ---------------------------------------------------------------------
// The body's sway: one slow signal for the whole figure.
//
// This used to be a random walk -- a fresh random target every few
// seconds, each bone reading the walk a beat later than the one below it.
// The idea behind it was right: a body that never settles reads as a
// person rather than as a prop.  The implementation was not.
//
// A random walk is jagged, and a jagged signal read at six different lags
// beats against itself.  The hips, the spine, the chest, the neck and the
// head each read the same walk a third of a second apart, and what the
// head ends up with is the sum of five jittery reads -- a fine tremor
// that never stops and never repeats.  The measured trace was exactly
// that: the pitch channel was never still, never rhythmic, and never the
// same shape twice, while the roll channel sat dead flat.  On a head
// that is most of the character's silhouette, that tremor reads as the
// one thing this whole layer exists to prevent -- a head that jitters.
//
// One signal for the whole figure, read by every bone a beat later than
// the one below it, so the weight travels up the body the way it does in
// a person: the hips go first, the spine answers, the chest follows, the
// neck and the head arrive last.
//
// The length of the noise cell is the length of one of its features, so
// this is roughly how long a drift of the body takes to happen.
const SWAY_CELL = 11.3
// The three axes are given three unrelated stretches of the noise.  They
// must not line up: two axes that rise and fall together describe a
// curve, and a head that keeps arriving at new points along a curve is
// a head going round in circles.
const SWAY_PHASE_PITCH = 0
const SWAY_PHASE_YAW = 17.3
const SWAY_PHASE_ROLL = 33.7
// How much of the posture noise reaches the figure at all.
//
// The posture is a texture, not a shape.  It is what stops the figure
// looking like a render being held between the deliberate movements, and
// it has to stay well under the size of those movements or the head ends
// up riding a slow drift that the eye reads as the character swaying.
const POSTURE_GAIN = 0.72

function swayValue(time: number, phase: number, amplitude: number, cell = SWAY_CELL) {
  // The length of the noise cell is the length of one of its features,
  // so it is how long a drift lasts.  The body drifts on eleven
  // seconds, which is about how long a shift of weight takes; the head
  // bobs on eight, which is about how long a person takes to settle
  // into a new stance.  The two lengths are different on purpose: on
  // the same length the head and the body would move as one object and
  // the whole figure would read as one slow pendulum.
  const x = time / cell + phase
  const middle = motionFbm(x, MOTION_SEED)
  const long = motionFbm(x * 0.19 + 3.7, MOTION_SEED + 41.3)
  // The slow octave pulled back out of the fast ones is what makes this
  // a wander around a pose rather than a walk across the room.
  return amplitude * (middle * 0.82 - long * 0.58)
}

// How much of the sway is showing right now.
//
// This is the difference between a figure that is standing and a figure
// that is performing.  A person at a counter is still for most of a
// minute; the movement arrives in waves, and between the waves almost
// nothing happens at all.  A character that sways at the same size the
// whole time reads as a metronome however organic each wave is, so the
// size of the sway runs through a slow gate which is shut most of the
// time and open for a stretch at a time.
//
// The gate is noise too, so it opens at irregular intervals and stays
// open for irregular lengths.  The floor is not zero: a figure that goes
// completely rigid between its waves reads as a render being held still,
// and a tenth of a degree of drift is enough to say otherwise.
const SWAY_FLOOR = 0.18

function swaySwell(time: number) {
  const n = motionFbm(time / 34.7 + 61.3, MOTION_SEED + 97.1)
  return SWAY_FLOOR + (1 - SWAY_FLOOR) * smoothstep((n + 0.08) / 0.4)
}

// Where the weight was at `time`, which is in the past for every bone
// above the hips.
//
// The cell is the length of the noise this bone reads.  It is per bone
// rather than shared, and the reason is the one that matters most for how
// the character reads: a single shared signal, read by five bones with
// three different lags between them, is a travelling wave, and a travelling
// wave through a torso ends up drawing a closed curve in the head's
// silhouette.  The eye sees that curve long before it sees anything else.
function samplePosture(time: number, out: THREE.Vector3, cell = SWAY_CELL) {
  const swell = swaySwell(time)
  out.set(
    swayValue(time, SWAY_PHASE_PITCH, 1, cell) * swell * POSTURE_GAIN,
    swayValue(time, SWAY_PHASE_YAW, 0.34, cell) * swell * POSTURE_GAIN,
    swayValue(time, SWAY_PHASE_ROLL, 0.85, cell) * swell * POSTURE_GAIN,
  )
  return out
}

// ---------------------------------------------------------------------
// The motion core.
//
// Everything the figure does while it is standing still is decided
// here: the walk it settles into, the small movements it makes while
// it is settled, and the numbers those two are built out of.
//
// It is one block on purpose.  The offline probe has to be able to run
// exactly what the browser runs, and a motion system scattered over
// four hundred lines of a component cannot be lifted whole, so it can
// only be measured by lifting the pieces -- and a probe that measures
// the pieces is measuring a different body from the one on screen.
//
// >>> YXZ MOTION CORE BEGIN
// Random bounded pose targets, damped transitions, and sparse head accents.
interface PoseAxis {
  /** Where it is now, in degrees. */
  pos: number
  /** Where it is going, in degrees. */
  want: number
  /** How fast it is travelling, in degrees a second. */
  vel: number
  /** When the pose is next redrawn. */
  next: number
  /** When the pose was first due, so that a reset can put it back. */
  first: number
  /** How far it may go from the middle. */
  limit: number
  /** How big a redraw usually is. */
  step: number
  /** The shortest a gap between two redraws may be. */
  gapMin: number
  /** The longest. */
  gapMax: number
  /** Controls the distribution of dwell lengths. */
  gapBias: number
}

function makeAxis(
  limit: number,
  step: number,
  gapMin: number,
  gapMax: number,
  gapBias: number,
  first: number,
) {
  return {
    pos: 0,
    want: 0,
    vel: 0,
    next: first,
    first,
    limit,
    step,
    gapMin,
    gapMax,
    gapBias,
  }
}

// The head is not a pendulum.  Keep the always-on posture layer small and
// let the sparse accents carry the readable movement.  The old larger
// values made three independent targets overlap into a continuous circle.
const headYaw: PoseAxis = makeAxis(0.48, 0.22, 4.50, 13.0, 1.30, 3.00)

const bodyRootPitch: PoseAxis = makeAxis(0.90, 0.32, 6.50, 22.0, 1.10, 2.20)
const bodyRootRoll: PoseAxis = makeAxis(1.20, 0.42, 7.00, 24.0, 1.10, 5.10)
const bodyRootYaw: PoseAxis = makeAxis(0.75, 0.28, 8.00, 27.0, 1.10, 7.40)
const bodyChainPitch: PoseAxis = makeAxis(0.72, 0.28, 5.00, 19.0, 1.10, 3.60)
const bodyChainRoll: PoseAxis = makeAxis(1.00, 0.36, 5.50, 20.0, 1.10, 6.20)
const bodyChainYaw: PoseAxis = makeAxis(0.65, 0.24, 6.00, 22.0, 1.10, 8.80)

const weightAxis: PoseAxis = makeAxis(0.80, 0.38, 9.00, 28.0, 1.10, 9.00)

const headAxes: PoseAxis[] = [headYaw]
const bodyAxes: PoseAxis[] = [
  bodyRootPitch,
  bodyRootRoll,
  bodyRootYaw,
  bodyChainPitch,
  bodyChainRoll,
  bodyChainYaw,
]
const allAxes: PoseAxis[] = [...headAxes, ...bodyAxes, weightAxis]

function poseGap(axis: PoseAxis) {
  const u = Math.random()
  const shaped = axis.gapBias <= 1
    ? u ** axis.gapBias
    : 1 - (1 - u) ** (1 / axis.gapBias)
  return axis.gapMin + shaped * (axis.gapMax - axis.gapMin)
}

function poseRedraw(axis: PoseAxis, time: number) {
  const big = Math.random() < 0.18
  const size = axis.step * (big ? 1.8 : 0.9) * (0.45 + Math.random() * 0.75)
  const direction = Math.random() < 0.5 ? -1 : 1
  let want = axis.want + direction * size
  if (Math.abs(want) > axis.limit)
    want = axis.want - direction * size * (0.45 + Math.random() * 0.2)
  axis.want = want
  axis.next = time + poseGap(axis)
}

const POSE_OMEGA = 2.65
const POSE_DAMPING = 0.88

function poseStep(axis: PoseAxis, delta: number) {
  const steps = Math.max(1, Math.ceil(delta * 120))
  const step = delta / steps
  for (let i = 0; i < steps; i++) {
    const acc = POSE_OMEGA * POSE_OMEGA * (axis.want - axis.pos)
      - 2 * POSE_DAMPING * POSE_OMEGA * axis.vel
    axis.vel += acc * step
    axis.pos += axis.vel * step
  }
}

let poseTime = -1

function poseDelta(time: number) {
  if (poseTime < 0) {
    poseTime = time
    return 0
  }
  const delta = time - poseTime
  poseTime = time
  if (!(delta > 0))
    return 0
  return Math.min(delta, 0.1)
}

const TEXTURE_YAW = 0.05

const poseTextureOut = { pitch: 0, yaw: 0, roll: 0 }

// The rock.
//
// The head's always-on movement is one line, and it has to be a line:
// a shape is something the eye can trace, and a traced shape is a loop,
// and a loop is the whole of the complaint about the head circling.
//
// What it was was a walk.  Each redraw stepped one more step in
// whichever direction it was already going and reflected off a limit,
// and a reflected walk is a slow triangle: it took the better part of
// half a minute to come and go.  Measured, ninety-three per cent of the
// head's movement sat below a twentieth of a hertz, which is a sway.
// The reference's movement sits in the band from a fifteenth of a hertz
// to a third, and ninety-three per cent of hers is in the lower half of
// that band, and the difference between the two is the difference
// between a character standing and a character breathing.
//
// But three sines at three unrelated frequencies is not a rock either.
// The reference's head is one waveform with its own harmonics riding
// on it, and it has been measured and taken apart: a fundamental at
// nought point zero nine six two hertz with the second, third, fourth
// and fifth harmonics on top of it, and every harmonic leaning between
// the chin and the tilt by its own amount.  The third harmonic leans
// the other way from the first, and that disagreement is most of why
// her head reads as a nod and a sway rather than as a wheel.
//
// So the rock is rebuilt out of those harmonics, at the amplitudes and
// the phases they were measured at.  The chin and the tilt are two sums
// rather than one number scaled by a ratio, because the harmonics
// disagree about the ratio: the two agree at the fundamental and they
// disagree at the fourth.  The turn is a third sum, and it leans with
// the chin at the fundamental and at the third, which is why she reads
// as turning with her nod instead of turning between her nods.
//
// The multiples are exact, and that matters more than it looks.  The
// harmonics have to keep their places against each other: pulled even a
// per cent apart, they slide through each other over a few minutes and
// arrive at a moment where all of them peak together, and the head
// takes a step of nine degrees in a tenth of a second.  Measured, the
// reference never takes a step like that; the ceiling on her is eight
// and a quarter, and a head that goes past its own ceiling is the
// difference between a person and a puppet.
//
// So the shape stays locked, and the loop is broken a different way: the
// tempo of the rock breathes, three per cent either way over
// forty-one seconds, so the cycle comes round at ten and a bit seconds
// one time and ten and a half the next, and never quite twice the
// same.  Every harmonic breathes with it, so the gesture stays one
// gesture.
const ROCK_BASE_FREQ = 0.0962
const ROCK_PHASE_ROOT = 1.7761
const ROCK_TEMPO_AMP = 0.025
const ROCK_TEMPO_PERIOD = 41
const ROCK_SWELL_AMP = 0.05
const ROCK_SWELL_PERIOD = 29
const ROCK_AMP_PITCH = [3.336, 0.7566, 1.3458, 0.0696, 0.1032]
const ROCK_AMP_ROLL = [4.723, 1.3189, 1.1525, 0.5213, 0.2179]
const ROCK_AMP_YAW = [0.2637, 0.0840, 0.3773, 0.0961, 0.2032]
const ROCK_PHASE_PITCH = [0, -4.71238898, 0, 1.54889963, 3.14159265]
const ROCK_PHASE_ROLL = [0, -4.71238898, 0, -1.57079633, 0]
const ROCK_PHASE_YAW = [0, -1.57079633, 0, -1.57079633, -3.14159265]
// What is written above, and what the bone does with it once the
// chain under the head has had its say.
const ROCK_GAIN_PITCH = 1.034
const ROCK_GAIN_ROLL = 0.990
const ROCK_GAIN_YAW = 1.0

// Where the rock's fundamental is in its cycle, and how fast it is going.
//
// The fundamental is the master: every harmonic is a whole number of
// times this angle, so the whole thing is one gesture and not five.
// The tempo term is what keeps it from being a recording: the angle
// runs at the reference's rate, and the rate itself drifts three per
// cent either way over forty-one seconds, so the cycle comes round a
// little early and a little late and never lands on the same moment
// twice.
function rockTheta(time: number) {
  const tempo = 2 * Math.PI * time / ROCK_TEMPO_PERIOD
  return 2 * Math.PI * ROCK_BASE_FREQ
    * (time - ROCK_TEMPO_AMP * ROCK_TEMPO_PERIOD / (2 * Math.PI) * Math.cos(tempo))
    + ROCK_PHASE_ROOT + MOTION_SEED * 0.001
}

function rockThetaRate(time: number) {
  const tempo = 2 * Math.PI * time / ROCK_TEMPO_PERIOD
  return 2 * Math.PI * ROCK_BASE_FREQ * (1 + ROCK_TEMPO_AMP * Math.sin(tempo))
}

// How big the rock is at this moment.
//
// A figure that sways at one size all the time is a metronome however
// organic each wave is.  The size of the sway has to come in and go
// out, and the swell is slow enough that it is a change of posture
// rather than a change of movement.
function rockSwell(time: number) {
  return 1 + ROCK_SWELL_AMP * Math.sin(2 * Math.PI * time / ROCK_SWELL_PERIOD + 1.3)
}

// The rock at one moment, all six numbers of it.
const rockSampleOut = {
  pitch: 0,
  roll: 0,
  yaw: 0,
  pitchVel: 0,
  rollVel: 0,
  yawVel: 0,
}

function rockSample(time: number) {
  const theta = rockTheta(time)
  const rate = rockThetaRate(time)
  const swell = rockSwell(time)
  let pitch = 0
  let roll = 0
  let yaw = 0
  let pitchVel = 0
  let rollVel = 0
  let yawVel = 0
  for (let i = 0; i < ROCK_AMP_PITCH.length; i++) {
    const harmonic = i + 1
    const phase = harmonic * theta
    const omega = harmonic * rate
    pitch += ROCK_AMP_PITCH[i] * Math.sin(phase + ROCK_PHASE_PITCH[i])
    roll += ROCK_AMP_ROLL[i] * Math.sin(phase + ROCK_PHASE_ROLL[i])
    yaw += ROCK_AMP_YAW[i] * Math.sin(phase + ROCK_PHASE_YAW[i])
    pitchVel += ROCK_AMP_PITCH[i] * omega * Math.cos(phase + ROCK_PHASE_PITCH[i])
    rollVel += ROCK_AMP_ROLL[i] * omega * Math.cos(phase + ROCK_PHASE_ROLL[i])
    yawVel += ROCK_AMP_YAW[i] * omega * Math.cos(phase + ROCK_PHASE_YAW[i])
  }
  rockSampleOut.pitch = pitch * ROCK_GAIN_PITCH * swell
  rockSampleOut.roll = roll * ROCK_GAIN_ROLL * swell
  rockSampleOut.yaw = yaw * ROCK_GAIN_YAW * swell
  rockSampleOut.pitchVel = pitchVel * ROCK_GAIN_PITCH * swell
  rockSampleOut.rollVel = rollVel * ROCK_GAIN_ROLL * swell
  rockSampleOut.yawVel = yawVel * ROCK_GAIN_YAW * swell
  return rockSampleOut
}

// How fast the rock is moving in the plane of the face.
function rockSpeedAt(time: number) {
  const sample = rockSample(time)
  return Math.hypot(sample.pitchVel, sample.rollVel)
}

function poseTexture(time: number) {
  poseTextureOut.yaw = motionFbm(time / 13.7 + 7.7, MOTION_SEED + 151.3) * TEXTURE_YAW
  poseTextureOut.pitch = 0
  poseTextureOut.roll = 0
  return poseTextureOut
}

const swayHead = { x: 0, y: 0, z: 0, speed: 0 }

const motionChainLean = { x: 0, y: 0, z: 0 }
const motionRootLean = { x: 0, y: 0, z: 0 }

function updateMotionLevels(time: number) {
  const delta = poseDelta(time)
  for (const axis of allAxes) {
    if (time >= axis.next)
      poseRedraw(axis, time)
    if (delta > 0)
      poseStep(axis, delta)
  }

  // The rock, as three sums rather than one.
  const rock = rockSample(time)
  const chin = rock.pitch
  const tilt = rock.roll
  const turn = rock.yaw
  const texture = poseTexture(time)
  swayHead.x = chin
  swayHead.y = headYaw.pos + turn + texture.yaw
  swayHead.z = tilt

  swayHead.speed = Math.hypot(rock.pitchVel, rock.rollVel, rock.yawVel + headYaw.vel)

  motionRootLean.x = bodyRootPitch.pos
  motionRootLean.y = bodyRootYaw.pos
  motionRootLean.z = bodyRootRoll.pos
  motionChainLean.x = bodyChainPitch.pos
  motionChainLean.y = bodyChainYaw.pos
  motionChainLean.z = bodyChainRoll.pos
}

interface HeadGestureSpec {
  kind: string
  pitch: [number, number]
  yaw: [number, number]
  roll: [number, number]
  /** How much of the pitch the tilt takes with it. */
  follow: number
  /** Which of the axes may go either way. */
  sign: string[]
  dur: [number, number]
  weight: number
}

const HEAD_GESTURES: HeadGestureSpec[] = [
  { kind: 'nod', pitch: [-0.9, -0.45], yaw: [0, 0.2], roll: [0, 0], follow: 0.75, sign: [], dur: [0.4, 0.68], weight: 1.1 },
  { kind: 'lift', pitch: [0.4, 0.8], yaw: [0, 0.2], roll: [0, 0], follow: 0.75, sign: [], dur: [0.45, 0.72], weight: 0.7 },
  { kind: 'tilt', pitch: [-0.25, 0.25], yaw: [0, 0.25], roll: [0.45, 0.9], follow: 0, sign: ['roll'], dur: [0.5, 0.78], weight: 0.9 },
  { kind: 'glance', pitch: [-0.2, 0.2], yaw: [0.22, 0.5], roll: [-0.15, 0.15], follow: 0, sign: ['yaw'], dur: [0.45, 0.72], weight: 0.8 },
]

interface HeadGesture {
  kind: string
  start: number
  dur: number
  pitch: number
  roll: number
  yaw: number
}

// The head has a ceiling on how fast it can move.
//
// The reference never takes a step faster than eight and a quarter
// degrees a second, and that ceiling is not a detail: it is what
// separates a head that is looking at something from a head that is
// being shaken.  The rock is already using most of it, so what the
// character decides to do has to fit in what is left.  A gesture that
// starts while the head is already moving at full speed is scaled
// down to the room there is rather than being laid on top of it and
// pushing the head past its own ceiling.
const HEAD_SPEED_CEILING = 8.4

// How fast the rock is going to be over the next little while.
//
// The peak is not now: the rock is on its way up, and a gesture that
// starts on the flat part of the wave is still on the crest of it by
// the time the gesture is over.
function rockSpeedOver(time: number, dur: number) {
  let peak = 0
  for (let i = 0; i <= 4; i++) {
    const sample = rockSpeedAt(time + dur * i / 4)
    if (sample > peak)
      peak = sample
  }
  return peak
}

// The fastest the gesture will move the head while it is playing.
function gesturePeakSpeed(gesture: HeadGesture) {
  const shape = Math.hypot(gesture.pitch, gesture.roll)
  return 0.532 * shape / (0.38 * Math.max(0.001, gesture.dur))
}

interface HeadGestureState {
  current: HeadGesture | null
  nextAt: number
  history: string[]
}

const headGestures: HeadGestureState = { current: null, nextAt: 1.2, history: [] }
let headGestureCount = 0

function nextHeadGestureGap() {
  const roll = Math.random()
  if (roll < 0.58)
    return 1.1 + Math.random() * 1.4
  if (roll < 0.90)
    return 2.5 + Math.random() * 2.4
  return 4.9 + Math.random() * 3.6
}

function pickHeadGesture(time: number, status: YXZStatus) {
  const shape = ATTENTION_SHAPE[status] ?? ATTENTION_SHAPE.idle
  const recent = headGestures.history.slice(-2)
  const fresh = HEAD_GESTURES.filter(gesture => !recent.includes(gesture.kind))
  const pool = fresh.length > 0 ? fresh : HEAD_GESTURES
  let total = 0
  for (const gesture of pool)
    total += gesture.weight * shape.scale
  let roll = Math.random() * total
  let chosen = pool.at(-1)
  for (const gesture of pool) {
    roll -= gesture.weight * shape.scale
    if (roll <= 0) {
      chosen = gesture
      break
    }
  }
  if (!chosen)
    return null
  const between = (bounds: [number, number]) =>
    bounds[0] + Math.random() * (bounds[1] - bounds[0])
  const sized = (bounds: [number, number]) => {
    const span = bounds[1] - bounds[0]
    return bounds[0] + span * Math.random() ** 1.5
  }
  const sign = (axis: string) => (chosen.sign.includes(axis) ? (Math.random() < 0.5 ? -1 : 1) : 1)
  const pitch = sized(chosen.pitch) * shape.scale
  const gesture: HeadGesture = {
    kind: chosen.kind,
    start: time,
    dur: between(chosen.dur),
    pitch,
    roll: chosen.follow > 0
      ? pitch * chosen.follow
      : sized(chosen.roll) * shape.scale * sign('roll'),
    yaw: sized(chosen.yaw) * shape.scale * sign('yaw'),
  }
  // Fit it in the room the head has left.
  //
  // The rock is the character breathing and the gesture is the
  // character noticing something, and a person who notices something
  // while breathing hard does not snap.  So the gesture is measured
  // against the speed the head is going to reach while it plays, and
  // scaled down to fit under the ceiling.
  const room = HEAD_SPEED_CEILING - rockSpeedOver(time, gesture.dur)
  const peak = gesturePeakSpeed(gesture)
  if (peak > room && peak > 0) {
    const shrink = Math.max(0, room / peak)
    gesture.pitch *= shrink
    gesture.roll *= shrink
    gesture.yaw *= shrink
  }
  headGestures.history.push(gesture.kind)
  if (headGestures.history.length > 6)
    headGestures.history.shift()
  return gesture
}

function headGestureShape(k: number) {
  if (k <= 0 || k >= 1)
    return 0
  const out = 0.38
  if (k < out) {
    const t = k / out
    return Math.sin(t * Math.PI * 0.5) ** 1.2
  }
  const t = (k - out) / (1 - out)
  return (1 - smoothstep(t)) * (1 + 0.12 * Math.sin(t * Math.PI * 2) * (1 - t))
}

// A gesture only happens on a calm head.
//
// The rock's speed is between one and seven degrees a second through
// most of its cycle and it is above five for a quarter of the time,
// and a gesture laid on top of the fast part of it is what used to
// take the head past the speed a neck can actually do.
const GESTURE_SPEED = 4.8

function updateHeadGestures(time: number, status: YXZStatus) {
  if (headGestures.current) {
    if ((time - headGestures.current.start) / headGestures.current.dur >= 1)
      headGestures.current = null
    return
  }
  if (time < headGestures.nextAt)
    return
  if (swayHead.speed > GESTURE_SPEED) {
    headGestures.nextAt = time + 0.3
    return
  }
  const gesture = pickHeadGesture(time, status)
  if (!gesture)
    return
  headGestures.current = gesture
  headGestureCount++
  headGestures.nextAt = time + gesture.dur + nextHeadGestureGap()
}

const headAccentEuler = new THREE.Euler()
const headAccentQuat = new THREE.Quaternion()
const headCycleQuat = new THREE.Quaternion()
const headCycleEuler = new THREE.Euler()

function updateHeadShape(time: number, status: YXZStatus, out: THREE.Quaternion, actionPitch: number, actionYaw: number, actionRoll: number) {
  updateMotionLevels(time)
  updateHeadGestures(time, status)
  let gesturePitch = 0
  let gestureRoll = 0
  let gestureYaw = 0
  if (headGestures.current) {
    const k = (time - headGestures.current.start) / headGestures.current.dur
    if (k >= 1) {
      headGestures.current = null
    }
    else {
      const shape = headGestureShape(k)
      gesturePitch = headGestures.current.pitch * shape
      gestureRoll = headGestures.current.roll * shape
      gestureYaw = headGestures.current.yaw * shape
    }
  }

  const aim = ATTENTION_GAIN[status] ?? 1
  headAccentEuler.set(
    THREE.MathUtils.degToRad(
      attentionNow.pitch * aim
      + gesturePitch
      + actionPitch,
    ),
    THREE.MathUtils.degToRad(attentionNow.yaw * aim + gestureYaw + actionYaw),
    THREE.MathUtils.degToRad(attentionNow.roll * aim + gestureRoll + actionRoll),
  )
  headAccentQuat.setFromEuler(headAccentEuler)

  // Compose the idle posture as a normal humanoid Euler pose.  Treating
  // pitch/yaw/roll as one axis-angle vector makes the rotation axis itself
  // orbit as the values change, which is perceived as the head circling.
  headCycleEuler.set(
    THREE.MathUtils.degToRad(swayHead.x),
    THREE.MathUtils.degToRad(swayHead.y),
    THREE.MathUtils.degToRad(swayHead.z),
    'YXZ',
  )
  headCycleQuat.setFromEuler(headCycleEuler)

  out.copy(headAccentQuat).multiply(headCycleQuat)
  return out
}

function lifeWeight(_time: number) {
  return weightAxis.pos
}

function resetMotion() {
  poseTime = -1
  for (const axis of allAxes) {
    axis.pos = 0
    axis.want = 0
    axis.vel = 0
    axis.next = axis.first
  }
  headGestures.current = null
  headGestures.nextAt = 1.2
  headGestures.history.length = 0
  headGestureCount = 0
  motionChainLean.x = 0
  motionChainLean.y = 0
  motionChainLean.z = 0
  motionRootLean.x = 0
  motionRootLean.y = 0
  motionRootLean.z = 0
  swayHead.x = 0
  swayHead.y = 0
  swayHead.z = 0
  swayHead.speed = 0
}

// <<< YXZ MOTION CORE END

// Choosing the next movement.
//
// Two rules do most of the work here.  The first is that a movement never
// follows itself: the last few are excluded unless there is nothing else
// left, because a character that glances aside and then, a few seconds
// later, glances aside again has shown the viewer its whole vocabulary.
// The second is that the gap is drawn from a power curve rather than a
// flat range, so most gaps are short and comfortable and every so often
// there is a long one -- and a long one is what makes the movements after
// it feel like the character did something rather than like it is on a
// timer.
function pickLifeAction(status: YXZStatus) {
  const bias = LIFE_ACTION_BIAS[status] ?? {}
  const recent = lifeHistory.slice(-2)
  const fresh = LIFE_ACTIONS.filter(action => !recent.includes(action.kind))
  const pool = fresh.length > 0 ? fresh : LIFE_ACTIONS
  if (pool.length === 0)
    return undefined
  let total = 0
  for (const action of pool)
    total += action.weight * (bias[action.kind] ?? 1)
  if (total <= 0)
    return pool.at(0)
  let roll = Math.random() * total
  for (const action of pool) {
    roll -= action.weight * (bias[action.kind] ?? 1)
    if (roll <= 0)
      return action
  }
  return pool.at(-1)
}

// How long to wait before doing anything.
//
// A single draw cannot make a casual figure, whatever curve it is drawn
// from, because casualness is not about the average gap -- it is about the
// fact that the gaps come in clumps.  People fidget for a few seconds,
// settle, and then stand still for half a minute, and then fidget again.
// Any steady rhythm, short or long, reads as a machine; the clump is the
// thing that reads as a person.
//
// So there are two modes here.  Most of the time the next movement is a
// proper stretch of nothing, shaped so that a long one turns up rarely and
// is worth reaching.  Roughly a quarter of the time the character has
// something to fumble with, and two or three small adjustments follow each
// other a couple of seconds apart before it settles again.
let lifeBurstLeft = 0

function nextLifeGap() {
  if (lifeBurstLeft > 0) {
    lifeBurstLeft--
    return 2.4 + Math.random() ** 1.5 * 4.8
  }
  // A quarter of the time something small happens almost at once.  The
  // gap between the movements is the thing that makes them read as a
  // person: not the frequency on its own, but the way the movements come
  // in clumps with long stretches between them.
  //
  // It used to be a third, and the clumps were tighter.  What that
  // produced was not a busier figure but a more broken one: the eye was
  // given a new piece of the pose every second or two and never got to
  // hold any of it, so nothing read as a movement that had a beginning
  // and an end.  Fewer, further apart, with the same shape.
  if (Math.random() < 0.24) {
    lifeBurstLeft = 1 + Math.floor(Math.random() ** 1.6 * 2)
    return 2.8 + Math.random() ** 1.5 * 4.4
  }
  return 7.5 + Math.random() ** 1.7 * 24
}

// The shape of a movement.
//
// Three things here are the difference between a joint rotating and a
// person moving, and none of them is the size of the angle:
//
//   lead    the movement starts by going the *other* way, briefly.  This
//           is the wind-up.  A head that turns without one is a servo.
//   out     the main stroke leaves fast and arrives slowly, so the eye
//           sees the movement start rather than seeing it already done.
//   return  the way back is slower than the way out, and it goes a little
//           past neutral before coming back.  The overshoot is small and
//           it is what stops the movement ending on a frame.
function actionEnvelope(k: number, action: LifeAction) {
  if (k <= 0 || k >= 1)
    return 0
  // The four phases of a movement have to fit inside the movement.
  //
  // They used to be laid out as: wind up, stroke, hold, and then whatever
  // was left over, with the stroke given `0.62 - lead - hold` of the time.
  // Every action with a long hold asked for more than that: the weight
  // shift wanted 0.28 of a wind-up and 0.42 of a hold, which is 0.70, and
  // the stroke was squeezed down to four percent of the movement.
  //
  // Four percent of three and a half seconds is a seventh of a second,
  // and a movement that reaches its full size in a seventh of a second is
  // not a movement, it is a twitch.  This is where the snapping came
  // from: the figure sat still, then jerked sideways, then sat still
  // again, and the eye reads that as a machine long before it has an
  // opinion about anything else.
  //
  // So the phases are laid out properly now.  The stroke is given a
  // guaranteed share of the movement, and the hold and the wind-up give
  // way when there is not enough room for it -- a shorter hold is barely
  // noticeable, a shorter wind-up is not even.
  let lead = THREE.MathUtils.clamp(action.lead, 0, 0.3)
  let hold = THREE.MathUtils.clamp(action.hold, 0, 0.42)
  const back = 0.3
  let out = 1 - lead - hold - back
  if (out < 0.18) {
    const deficit = 0.18 - out
    const fromHold = Math.min(deficit, hold * 0.75)
    hold -= fromHold
    const fromLead = Math.min(deficit - fromHold, lead * 0.6)
    lead -= fromLead
    out = 1 - lead - hold - back
  }
  const a1 = lead
  const a2 = lead + out
  const a3 = a2 + hold
  if (k < a1)
    return -0.14 * smoothstep(k / a1)
  if (k < a2) {
    const t = (k - a1) / out
    // A raised cosine.  It has no corner in it at either end, and its
    // fastest moment is in the middle of the stroke rather than at the
    // start of it.
    //
    // The old curve was a two-and-a-half power ease-out, which is at its
    // very fastest in the first fifth of the stroke -- which is exactly
    // where the eye is looking, and which is why the movement read as a
    // snap even when the total angle was small.  The quintic that
    // replaced it was better but still peaked at nearly twice the
    // average speed of the stroke; the raised cosine peaks at one and a
    // half, and one and a half is what a person's own movement does.
    return -0.14 + 1.14 * (0.5 - 0.5 * Math.cos(Math.PI * t))
  }
  if (k < a3) {
    // Held, with the muscles giving back a little rather than a hard stop.
    const t = (k - a2) / hold
    return 1 - 0.06 * t
  }
  const t = (k - a3) / (1 - a3)
  const release = 0.94 * (1 - smoothstep(t))
  const overshoot = -0.08 * Math.sin(Math.PI * t) * smoothstep((t - 0.5) / 0.5)
  return release + overshoot
}

// The bones the head hangs off, and which of them the head takes with
// it when they move.
const HEAD_CHAIN = ['hips', 'spine', 'chest', 'upperChest']

function chainInheritance() {
  let pitch = 0
  let yaw = 0
  let roll = 0
  for (const name of HEAD_CHAIN) {
    const index = lifeBoneIndex.get(name)
    if (index === undefined)
      continue
    pitch += lifeMoveDeg[index * 3]
    yaw += lifeMoveDeg[index * 3 + 1]
    roll += lifeMoveDeg[index * 3 + 2]
  }
  return { pitch, yaw, roll }
}

function applyLifeLayer(delta: number) {
  if (lifeBones.length === 0 || !lifeEnabled)
    return
  lifeClock += delta
  const time = lifeClock
  const weight = LIFE_STATE_WEIGHT[props.status] ?? 1
  const aim = ATTENTION_GAIN[props.status] ?? 1
  const stillBones = activeAction
    ? clipStillBones.get(activeAction.getClip().name)
    : undefined
  const ownedBones = activeAction
    ? clipOwnedBones.get(activeAction.getClip().name)
    : undefined
  const clipName = activeAction?.getClip().name ?? ''

  updateAttention(time, props.status)

  if (!lifeMove && time >= lifeNextAt) {
    const action = pickLifeAction(props.status)
    if (action) {
      lifeMove = { action, start: time, side: Math.random() < 0.5 ? -1 : 1 }
      lifeHistory.push(action.kind)
      if (lifeHistory.length > 8)
        lifeHistory.shift()
      lifeNextAt = time + action.dur + nextLifeGap()
    }
    else {
      lifeNextAt = time + 2
    }
  }

  lifeGazeTurn.set(0, 0)
  lifeMoveDeg.fill(0)
  lifeGazeStrength = 0
  if (lifeMove) {
    const k = (time - lifeMove.start) / lifeMove.action.dur
    if (k >= 1) {
      lifeMove = null
    }
    else {
      const amount = actionEnvelope(k, lifeMove.action)
      for (const channel of lifeMove.action.channels) {
        const index = lifeBoneIndex.get(channel.bone)
        if (index === undefined)
          continue
        const side = channel.side ?? lifeMove.side
        const degrees = channel.deg * amount * side
        lifeMoveDeg[index * 3 + channel.axis] += degrees
        // A nod dips the eyes with it.  Small, but it is the difference
        // between a head that moves and a face that agrees with it.
        if (channel.bone === 'head') {
          if (channel.axis === 1)
            lifeGazeTurn.x += degrees
          else if (channel.axis === 0)
            lifeGazeTurn.y += degrees
        }
      }
      lifeGazeStrength = lifeMove.action.gaze * THREE.MathUtils.clamp(amount, 0, 1)
    }
  }

  // What the torso is doing, that the head has to go along with.
  //
  // The head is solved against the world, which is what keeps it on the
  // reference's own trajectory.  The price of that is that it does not
  // inherit the body's movement: when the figure leans, the lean stops
  // at the shoulders and the head stays exactly where it was.  That is
  // a neck bending by itself, and it is the other half of the puppet.
  //
  // So the head is handed the torso's share of the movement directly.
  // The neck is not in the list: it is the head's own frame, and the
  // head already moves with it.
  const inherit = chainInheritance()

  const breath = lifeBreath(time)
  // The walks, read once for the whole frame.
  //
  // Every bone in a frame agrees about which way the character is
  // leaning, because they all read the same two numbers.  A figure
  // whose hips read one signal and whose head reads another is two
  // things wearing one body.
  updateMotionLevels(time)
  // The weight, and the bones that take it.
  //
  // This is the one signal the whole figure is built out of.  It is
  // read here, once, and given to the hips, the spine above them, the
  // neck, and the legs and feet below -- so that the head, which hangs
  // off all of it, is carried by the same movement as the body instead
  // of making a movement of its own inside a still body.
  const weightShift = lifeWeight(time)
  for (const bone of lifeBones) {
    // Bones the clip holds still are left alone: the mixer will not rewrite
    // them, so anything written here would only ever accumulate.  A bone
    // the clip has been stripped of entirely is the exception: it is the
    // only thing driving that bone now, so it is written from `base`.
    const owned = ownedBones?.has(bone.node.name) === true
    if (!owned && stillBones?.has(bone.node.name)) {
      continue
    }
    samplePosture(time - bone.lag, postureSample, bone.cell)
    const tremor = lifeMicro(time, bone.phase) * bone.micro
    // The lean.
    //
    // The chain from the spine to the neck reads the reference's own
    // neck -- what she does on top of her root -- and takes its share
    // of it.  The hips are the root itself, and they read it whole.
    //
    // Nothing here is the head.  The head is solved for further down,
    // from where it has to end up, and the lean of the body is only
    // the body.
    const chain = bone.drive === 'body' ? bone.gain : 0
    lifeOffset.set(
      (bone.drift * lifeDrift(time, bone.rate, bone.phase, 0)
        + (bone.drive === 'body' ? 0 : postureSample.x * bone.gain)
        + tremor
        + breath * bone.breath) * weight,
      (bone.drift * lifeDrift(time, bone.rate, bone.phase, 1)
        + (bone.drive === 'body' ? 0 : postureSample.y * bone.gain)) * weight,
      (bone.drift * lifeDrift(time, bone.rate, bone.phase, 2)
        + (bone.drive === 'body' ? 0 : postureSample.z * bone.gain)) * weight,
    )
    if (chain !== 0) {
      lifeOffset.x += motionChainLean.x * chain * weight
      lifeOffset.y += motionChainLean.y * chain * weight
      lifeOffset.z += motionChainLean.z * chain * weight
    }
    // The body carries the head.
    //
    // The head has a slow movement of its own and the body has one of
    // its own, and for a long time they were two unrelated signals.
    // That is what put a moving head on a standing body, and it is why
    // the figure read as a puppet with a face on it rather than as
    // somebody standing there.
    //
    // So the body takes a share of the head's movement.  What the head
    // keeps over and above its share is what still reads as the head
    // being the head, and the part it gives away is what makes the
    // figure look like one piece instead of a head balanced on a prop.
    if (bone.lead) {
      lifeOffset.x += swayHead.x * bone.lead
      lifeOffset.z += swayHead.z * bone.lead
    }
    // The hips are the reference's root.
    if (bone.node.name === 'hips') {
      lifeOffset.x += motionRootLean.x * weight
      lifeOffset.y += motionRootLean.y * weight
      lifeOffset.z += motionRootLean.z * weight
    }
    if (bone.sway.roll !== 0 || bone.sway.yaw !== 0 || bone.sway.pitch !== 0) {
      lifeOffset.x += bone.sway.pitch * weightShift
      lifeOffset.y += bone.sway.yaw * weightShift
      lifeOffset.z += bone.sway.roll * weightShift
    }
    const index = lifeBoneIndex.get(bone.node.name)
    if (index !== undefined) {
      lifeOffset.x += lifeMoveDeg[index * 3] * weight
      lifeOffset.y += lifeMoveDeg[index * 3 + 1] * weight
      lifeOffset.z += lifeMoveDeg[index * 3 + 2] * weight
    }
    // The body goes with the look.
    //
    // A fraction of the head's turn is given to the spine, the chest and
    // the shoulders, so the character turns to look at something as a
    // whole rather than swivelling a head on top of a still body.  The
    // head gives the same fraction back by solving for where it has to
    // end up, so the turn it ends up making is the one that was asked
    // for and the body's share of it is the body's.
    if (bone.follow > 0)
      lifeOffset.y += attentionNow.yaw * bone.follow * aim
    // The head, solved for.
    //
    // Where the head has to end up is known: the reference's cycle, the
    // small movements, the attention and the body gesture that is
    // carrying it, all composed into one world rotation.  What is not
    // known is which way the head's own bone has to turn to get there,
    // because that depends on what the chain below it is doing.
    //
    // So it is worked backwards.  The parent is asked where it is now,
    // the target is taken back into the head's own space, and the head's
    // bone is given the rotation that puts it there.  The head ends up
    // exactly on the reference's trajectory whatever the body is doing
    // underneath it, which is the whole point: the old version added a
    // chain of rotations together and got something two fifths too deep
    // and half again too fast, and when a body gesture came through the
    // same chain on top of it the head went down eight and a half
    // degrees in a movement she would have made with her chin.
    if (bone.node === lifeHeadNode.current) {
      const headIndex = lifeBoneIndex.get(bone.node.name) ?? 0
      updateHeadShape(
        time,
        props.status,
        headShapeSample,
        lifeMoveDeg[headIndex * 3] * weight + inherit.pitch * weight,
        lifeMoveDeg[headIndex * 3 + 1] * weight + inherit.yaw * weight,
        lifeMoveDeg[headIndex * 3 + 2] * weight + inherit.roll * weight,
      )
      // The pose the mixer left the head in, which is the pose the
      // target is measured from.
      if (owned && bone.ownedBy !== clipName) {
        bone.base.copy(bone.node.quaternion)
        bone.ownedBy = clipName
      }
      const base = owned ? bone.base : bone.node.quaternion
      // Where the head's parent is right now.
      if (bone.node.parent)
        chainWorldQuaternion(bone.node.parent, lifeParentWorld)
      else
        lifeParentWorld.identity()
      // The head's own bone.
      //
      // The parent's turn is *not* undone.  It used to be, and that was
      // the last thing standing between the figure and being one piece:
      // the head was solved against the world, so the neck could turn
      // three degrees underneath it while the head stayed exactly where
      // it was -- and a neck that turns under a head that does not is a
      // broken joint, seen from every angle.  It was the same fault the
      // puppet had, one joint higher up.
      //
      // So the head now carries the neck.  The neck's turn relative to
      // its own rest pose is taken out of the chain and put on the
      // outside of the head's own movement, which means the head's aim
      // is still the aim -- the eyes are aimed separately and stay on
      // target -- while the head itself travels with the body.  The
      // figure swings as one, and the head is still the head.
      lifeLocal
        .copy(bone.restParentInv)
        .multiply(headShapeSample)
        .multiply(bone.restParent)
        .multiply(base)
      bone.node.quaternion.copy(lifeLocal)
      continue
    }

    // Authored in world axes and carried into the bone's own space, so a
    // nod is a nod and a turn is a turn no matter what the body is doing.
    lifeEuler.set(
      THREE.MathUtils.degToRad(lifeOffset.x),
      THREE.MathUtils.degToRad(lifeOffset.y),
      THREE.MathUtils.degToRad(lifeOffset.z),
    )
    lifeWorld.setFromEuler(lifeEuler)
    // The offset is a world-space rotation, and the parent's live motion
    // is taken out of it rather than put into it, so the bone travels
    // with the body and the offset stays a rotation of the bone.
    //
    // The ring used to be pinned: it was solved into the parent's *rest*
    // frame, which cancelled the parent's motion entirely and left the
    // ring standing perfectly level while the body turned under it.  A
    // ring that does not tilt with the shoulders is a decal, and the
    // shoulders are the biggest thing moving.  Conjugating by the
    // parent's rest rotation and keeping its live rotation outside --
    // which is what this does -- gives the ring the body's motion and
    // none of the end-over-end flipping that pinning was meant to avoid.
    lifeLocal.copy(bone.restParentInv).multiply(lifeWorld).multiply(bone.restParent)
    if (owned) {
      // The mixer wrote this bone once, when the clip started, and will
      // not write it again.  That one write is the pose everything else
      // is measured from, so take it as the base and start from there.
      if (bone.ownedBy !== clipName) {
        bone.base.copy(bone.node.quaternion)
        bone.ownedBy = clipName
      }
      bone.node.quaternion.copy(bone.base).premultiply(lifeLocal)
    }
    else {
      bone.node.quaternion.premultiply(lifeLocal)
    }
  }
}

// ---------------------------------------------------------------------
// The gaze.
//
// The eyes are the fastest thing on the character and the thing the
// viewer watches most, and locking them to the camera -- which is what
// this used to do, with a small random offset re-picked once a second --
// gives a stare.  What makes a held gaze read as a gaze is that the eyes
// are never quite still inside it: they land on something, hold, and then
// make a small jump to something nearby a beat later, several times a
// minute.  The jumps are tiny and fast, which is exactly what a real
// microsaccade is.
//
// On top of that sits the slow wander of what the character is looking
// *at*: a point near the viewer that moves every few seconds, so over a
// minute it is not staring at one pixel, and during a head movement the
// eyes go with the head rather than staying glued to the lens.
const gazeAnchor = new THREE.Vector3()
const gazeWander = new THREE.Vector2()
const gazeFixation = new THREE.Vector3(0, 2.1, 8.8)
const gazeFrom = new THREE.Vector3(0, 2.1, 8.8)
const gazeNear = new THREE.Vector3(0, 2.1, 8.8)
const gazeDesired = new THREE.Vector3(0, 2.1, 8.8)
const gazeTemp = new THREE.Vector3()
const gazeEuler = new THREE.Euler()
const gazeQuat = new THREE.Quaternion()
let gazeMoveStart = -10
let gazeMoveDur = 0.09
let gazeNextSaccadeAt = 0.5
let gazeNextWanderAt = 0
// The eyes are the fast one.  A head turn reads as looking rather than
// as swivelling only when the eyes are already most of the way there by
// the time the head arrives, so this is how far along its own trip the
// eyes are allowed to run at the head's current pace.
const GAZE_LEAD = 0.09

function updateGaze(delta: number, time: number) {
  const lookAt = vrm?.lookAt
  if (!lookAt || !camera)
    return
  camera.getWorldPosition(cameraWorldPosition)

  // The slow part: where, roughly, the character is attending.  It moves
  // on a long timer and by a small amount, because the point of it is
  // only that the gaze is not nailed to the lens.
  if (time >= gazeNextWanderAt) {
    gazeWander.set(
      (Math.random() * 2 - 1) * 0.26,
      (Math.random() * 2 - 1) * 0.18,
    )
    gazeNextWanderAt = time + 4.5 + Math.random() * 8
  }
  gazeAnchor.copy(cameraWorldPosition)
  gazeAnchor.x += gazeWander.x
  gazeAnchor.y += gazeWander.y

  // The head's aim is folded into the point the eyes are attending, so the
  // two always agree: when the character has decided it is looking at
  // something off to one side, the eyes go there with it and then stay
  // there, and the tiny saccades below happen around that held point rather
  // than dragging it back to the lens.  Aiming them separately is what makes
  // a character's eyes look like they belong to a different character from
  // the one wearing them.
  //
  // The eyes lead on the way out and trail on the way back, so the turn
  // reads as looking rather than as swivelling.
  if (lifeHeadNode.current) {
    chainWorldPosition(lifeHeadNode.current, lifeWorldPosition)
    gazeTemp.copy(gazeAnchor).sub(lifeWorldPosition)
    const range = Math.max(1, gazeTemp.length())
    const follow = lifeGazeStrength
    // The eyes sit a short way ahead of the head while it is travelling and
    // exactly on it once it has arrived, which is what makes a turn read as
    // looking somewhere rather than as a head swivelling.
    const ahead = attentionStart >= 0
      ? THREE.MathUtils.clamp((time - attentionStart) / Math.max(0.001, attentionDur * GAZE_LEAD), 0, 1)
      : 1
    gazeEuler.set(
      THREE.MathUtils.degToRad(
        attentionNow.pitch
        + (attentionTo.pitch - attentionNow.pitch) * ahead
        + lifeGazeTurn.y * follow,
      ),
      THREE.MathUtils.degToRad(
        attentionNow.yaw
        + (attentionTo.yaw - attentionNow.yaw) * ahead
        + lifeGazeTurn.x * follow,
      ),
      0,
      'YXZ',
    )
    gazeQuat.setFromEuler(gazeEuler)
    gazeTemp.setLength(range).applyQuaternion(gazeQuat)
    gazeAnchor.copy(lifeWorldPosition).add(gazeTemp)
  }

  // The fast part: a new fixation a short way from the current one.  These
  // are the jumps that keep a held gaze alive.  They are deliberately
  // small -- a real microsaccade is a fraction of a degree -- but they are
  // frequent enough that the eyes are never frozen.
  if (time >= gazeNextSaccadeAt) {
    const reach = 0.05 + Math.random() * 0.07
    gazeNear.copy(gazeAnchor)
    gazeNear.x += (Math.random() * 2 - 1) * reach
    gazeNear.y += (Math.random() * 2 - 1) * reach * 0.8
    gazeNextSaccadeAt = time + 0.22 + Math.random() ** 2 * 1.6
  }

  // The point the eyes want, and the jump that gets them there.
  //
  // Every eye movement is a jump, not a slide: the fixations are picked
  // first and the eyes arrive at them in about sixty milliseconds, which
  // is short enough that the travel is not something the eye follows.
  // Sliding between them instead is what makes a rendered gaze read as a
  // camera drifting.  The jump restarts whenever the wanted point has
  // moved far enough to be worth another one, which is what carries the
  // eyes out to a glance and back without the jump timer having to know
  // anything about glances at all.
  gazeDesired.copy(gazeNear)
  if (gazeFixation.distanceToSquared(gazeDesired) > 4e-4) {
    gazeFrom.copy(gazeFixation)
    gazeMoveStart = time
    // A saccade while holding is a jump nobody follows; one thrown across a
    // head turn has to be quicker, or the eyes visibly lag the head.
    gazeMoveDur = attentionStart >= 0 ? 0.06 : 0.05 + Math.random() * 0.03
  }
  const k = THREE.MathUtils.clamp((time - gazeMoveStart) / Math.max(0.001, gazeMoveDur), 0, 1)
  gazeFixation.copy(gazeFrom).lerp(gazeDesired, smoothstep(k))

  if (!lookAt.target)
    lookAt.target = new THREE.Object3D()
  lookAt.target.position.copy(gazeFixation)
  lookAt.update(delta)
}

// ---------------------------------------------------------------------
// Blinking.
//
// A blink on a uniform timer is the most mechanical thing a face can do,
// because a uniform timer is exactly what it is.  Three things break it
// up: the interval is drawn from a curve rather than a range, one blink
// in six is followed almost immediately by a second, and one blink in
// seven is a slow half-lidded one -- which reads as the character being
// relaxed rather than as a texture animation running on a timer.
let blinkTime = 0
let blinkStart = -1
let blinkDuration = 0.19
let blinkQueue = 0
let blinkNextAt = 2

function updateBlink(delta: number) {
  const manager = vrm?.expressionManager
  if (!manager)
    return
  blinkTime += delta
  if (blinkStart < 0) {
    if (blinkTime < blinkNextAt) {
      manager.setValue('blink', 0)
      return
    }
    blinkStart = blinkTime
    blinkDuration = Math.random() < 0.14 ? 0.42 : 0.19
    if (blinkQueue === 0 && Math.random() < 0.18)
      blinkQueue = Math.random() < 0.3 ? 2 : 1
  }
  const k = (blinkTime - blinkStart) / blinkDuration
  if (k >= 1) {
    manager.setValue('blink', 0)
    blinkStart = -1
    if (blinkQueue > 0) {
      blinkQueue--
      blinkNextAt = blinkTime + 0.09 + Math.random() * 0.08
    }
    else {
      blinkNextAt = blinkTime + 1.9 + Math.random() ** 1.6 * 6.2
    }
    return
  }
  // Fast shut, a beat shut, a slower opening.  A blink that opens at the
  // same speed it closes is a rectangle.
  const raw = k < 0.34
    ? smoothstep(k / 0.34)
    : k < 0.52
      ? 1
      : 1 - smoothstep((k - 0.52) / 0.48)
  manager.setValue('blink', raw * raw * (3 - 2 * raw))
}

function updateVisemes(delta: number, phase: number) {
  const manager = vrm?.expressionManager
  if (!manager)
    return
  const speaking = props.status === 'speaking' && !props.paused
  const measured = THREE.MathUtils.clamp(props.speakingLevel, 0, 1)
  if (speaking) {
    visemeClock += delta
    // Roughly one vowel per 200ms reads as speech without buzzing.  Slower
    // than the original 150ms: the auto-generated mouth morphs are small,
    // and a fast cycle on top of the quiet body pose reads as fidgeting.
    if (visemeClock >= 0.2) {
      visemeClock -= 0.2
      visemeIndex = (visemeIndex + 1) % VISEMES.length
    }
  }
  // Browser speech synthesis exposes no analyser node, so fall back to a
  // gentle pulse rather than leaving the mouth shut.
  const target = speaking
    ? (measured > 0 ? measured : 0.22 + Math.max(0, Math.sin(phase * 7.5)) * 0.3) * (reducedMotion ? 0.82 : 1)
    : 0
  const smoothing = 1 - Math.exp(-delta * 18)
  mouthEnvelope = THREE.MathUtils.lerp(mouthEnvelope, target, smoothing)
  // Cap the morph weight well below full: the generated viseme shapes move
  // the whole lower face region and at weight 1.0 they read as distortion.
  // 0.45 keeps the mouth readable as speech without the jaw looking pulled.
  const weight = mouthEnvelope > 0.12 ? THREE.MathUtils.clamp(mouthEnvelope * 0.45, 0, 0.45) : 0
  VISEMES.forEach((name, index) => {
    manager.setValue(name, index === visemeIndex ? weight : 0)
  })
}

function animate(now: number) {
  if (!renderer || !scene || !camera || !actor)
    return
  const seconds = now / 1000
  // Reduced motion should soften the performance, not freeze the character.
  // A frozen avatar is especially confusing in an interactive exhibition,
  // where visitors read movement as feedback that it is alive.
  const still = props.paused
  const motionScale = reducedMotion ? 0.82 : 1
  const phase = still ? 0 : seconds
  const delta = lastFrameAt > 0 ? Math.min((now - lastFrameAt) / 1000, 0.1) : 0
  lastFrameAt = now
  frameCount++

  // Entrance: float up, settle, one small squash-and-bounce. Runs once after
  // mount, in wall-clock time, and is fully reverted so nothing downstream
  // ever sees a lingering offset.
  if (introStart >= 0) {
    const introT = Math.min(1, (now - introStart) / INTRO_DURATION_MS)
    const settle = 1 - Math.pow(1 - introT, 3)
    // Rise in the first third, then a soft landing bounce on the last third.
    const bouncePhase = Math.max(0, (introT - 0.62) / 0.38)
    const bounce = Math.sin(Math.min(1, bouncePhase) * Math.PI)
    actor.position.y = -0.62 * (1 - settle) + 0.05 * bounce
    if (vrmGroup) {
      const squash = 1 + 0.075 * bounce
      vrmGroup.scale.set(1 / Math.sqrt(squash), squash, 1 / Math.sqrt(squash))
    }
    if (introT >= 1) {
      actor.position.y = 0
      if (vrmGroup)
        vrmGroup.scale.set(1, 1, 1)
      introStart = -2
    }
  }

  if (!poseFrozen)
    mixer?.update(still ? 0 : delta * motionScale * lifeTimeScale)
  // The living layer runs on top of whatever the clip is doing, and it
  // runs before the spring bones so that hair and cloth settle against
  // the pose the body is actually in.
  if (!still)
    applyLifeLayer(delta * motionScale * lifeTimeScale)
  // And the authored gestures are scheduled on the same clock, so that
  // they wait for a gap in the behaviour rather than cutting across it.
  if (!still)
    updateOneShots(lifeClock)
  guardModelShape(seconds)

  // Mirror the update order AIRI's own VRM stage uses, because we own the
  // render loop instead of letting a framework drive it.
  if (vrm) {
    // `humanoid.update()` is a no-op for the bones now that
    // `autoUpdateHumanBones` is off, but it still keeps the humanoid in
    // step with the rest of the VRM components.
    vrm.humanoid?.update()
    emote?.update(delta)
    if (!still) {
      updateGaze(delta, lifeClock)
      updateBlink(delta)
    }
    else {
      vrm.expressionManager?.setValue('blink', 0)
    }
    updateVisemes(still ? 0 : delta, phase)
    vrm.expressionManager?.update()
    vrm.nodeConstraintManager?.update()
    vrm.springBoneManager?.update(delta)
  }

  // The shadow map is rebuilt by the render itself, and `autoUpdate` is off,
  // so it has to be flagged once per frame.  Flagging it here keeps the
  // shadows identical from frame to frame while paying for them a single
  // time.
  renderer.shadowMap.needsUpdate = true
  if (composer)
    composer.render(delta)
  else
    renderer.render(scene, camera)
  animationFrame = requestAnimationFrame(animate)
}

onMounted(async () => {
  if (!canvasContainer.value)
    return
  readMotionFlags()
  componentState.value = 'loading'
  const token = ++loadToken
  try {
    scene = new THREE.Scene()
    // The near plane is the one number that decides how finely the depth
    // buffer can separate two surfaces.  At 0.01 the resolution at the
    // character's distance is about half a millimetre of world space,
    // which is the same order as the gaps between the doubled sheets of
    // the scan, and any two of them then fight for the same pixel.  The
    // camera never comes closer than about five units, so 0.5 costs
    // nothing and buys fifty times the depth precision.
    camera = new THREE.PerspectiveCamera(30, 1, 0.5, 100)
    // The camera sits close to the character's eye line.  The model is a
    // chibi with a very large head, so its eyes sit high; a camera at the
    // body's middle makes the character look down at the viewer, and the
    // gaze then has to fight a permanent downward tilt for every clip.
    camera.position.set(0, 2.25, 8.8)
    camera.lookAt(0, 2.05, 0)
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'high-performance' })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5))
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.0
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFShadowMap
    // Manual updates, so the shadow map is rebuilt exactly once per frame
    // instead of once per pass.
    renderer.shadowMap.autoUpdate = false
    canvasContainer.value.appendChild(renderer.domElement)

    // MToon is a toon shader: it reads diffuse plus rim and has no specular
    // lobe, which is exactly why it avoids the plastic/glass look. The shell
    // is nearly white and it stands on a nearly white page, so the budget
    // here is deliberately tight: too much ambient washes the cel terminator
    // away and the character flattens into a white blob with no readable
    // form.  The key light carries the shape, the hemisphere only keeps the
    // shadow side from going flat black, and the cyan point is a small
    // accent on the left edge rather than a second key.
    //
    // The colours are what stop a white character from reading as a white
    // toy.  A white key on a white body gives a white result, so the lit
    // side is warmed the way daylight is and the shadow side is filled with
    // a cool sky bounce; the difference between the two is what the eye
    // reads as shape.
    const hemisphere = new THREE.HemisphereLight(0xEAF3FF, 0x1E2E46, 0.26)
    hemisphere.name = 'hemisphere'
    scene.add(hemisphere)
    const key = new THREE.DirectionalLight(0xFFF2E2, 1.9)
    key.name = 'key'
    key.position.set(3.2, 4.8, 4.8)
    key.castShadow = true
    // The frustum is fitted to the character rather than left loose.
    // Nothing but the character and the ground it stands on is ever in
    // it, so every texel of the map is a texel of the figure, and the
    // shadow it casts on the floor is twice as finely sampled for the
    // same memory.
    key.shadow.mapSize.set(2048, 2048)
    key.shadow.camera.near = 0.1
    key.shadow.camera.far = 12
    key.shadow.camera.left = -2.6
    key.shadow.camera.right = 2.6
    key.shadow.camera.top = 4.2
    key.shadow.camera.bottom = -1.2
    key.shadow.bias = -0.0006
    // A depth bias alone cannot keep the crevice under the helmet rim free
    // of acne, because the surfaces there are nearly parallel to the light
    // and the depth offset it needs is larger than the crevice itself.  A
    // normal bias moves the shadow lookup along the surface normal, which
    // keeps the shadow in place and removes the speckle.
    key.shadow.normalBias = 0.03
    // `PCFSoftShadowMap` is deprecated in three r183 and silently falls back
    // to this filter anyway; the radius is what softens the edge.
    key.shadow.radius = 4
    key.shadow.camera.updateProjectionMatrix()
    scene.add(key)
    // Cool fill from the opposite side keeps the shadow side readable without
    // washing out the terminator.
    const fill = new THREE.DirectionalLight(0x9EC2FF, 0.22)
    fill.name = 'fill'
    fill.position.set(-4, 2.4, 2.8)
    scene.add(fill)
    // The wings are the one part of the character that faces the camera and
    // not the key.  They are near-horizontal sheets either side of the
    // torso, so the key rakes along them instead of landing on them, and
    // with the body's own shade already deepened to keep the cel ramp
    // readable they come out a flat grey -- grey wings on a white
    // character read as unfinished, which is the opposite of what the
    // design calls for.  A soft frontal fill only reaches surfaces that
    // are turned towards the viewer and away from the key, so it lifts the
    // wings and the flat plates on the shoulders without touching the
    // terminator on the body, which is already lit from the front.
    const frontal = new THREE.DirectionalLight(0xE8F1FF, 0.18)
    frontal.name = 'frontal'
    frontal.position.set(5.5, 0.4, 1.1)
    scene.add(frontal)
    const rim = new THREE.PointLight(0x8FD8FF, 0.95, 8)
    rim.name = 'rim'
    rim.position.set(-3.2, 2.9, 2.2)
    scene.add(rim)
    // A dim warm bounce from below, the way a white page would light the
    // underside of a figure standing on it.  Without it the lower half of
    // the character goes flat and cold, and the whole figure reads as
    // cut out rather than lit.
    const bounce = new THREE.PointLight(0xFFE0BC, 0.30, 12)
    bounce.name = 'bounce'
    bounce.position.set(0.6, -1.4, 3.4)
    scene.add(bounce)
    const groundShadow = new THREE.Mesh(
      new THREE.CircleGeometry(1.65, 64),
      new THREE.ShadowMaterial({ color: 0x0B4261, opacity: 0.16 }),
    )
    groundShadow.rotation.x = -Math.PI / 2
    groundShadow.position.y = 0.43
    groundShadow.receiveShadow = true
    scene.add(groundShadow)
    actor = new THREE.Group()
    scene.add(actor)

    // Three skips tone mapping whenever it draws into a render target, so the
    // composer chain stays linear until `OutputPass` converts it back. Leaving
    // `renderer.toneMapping` set is therefore what keeps the look unchanged.
    //
    // The composer's own buffer carries the multisampling, because the
    // canvas' `antialias` only covers what the renderer draws straight to
    // the screen -- the beauty pass goes into a render target, and it is the
    // beauty pass's edge that decides how clean the silhouette outline is.
    const width = Math.max(1, canvasContainer.value.clientWidth)
    const height = Math.max(1, canvasContainer.value.clientHeight)
    const composerTarget = new THREE.WebGLRenderTarget(
      width * renderer.getPixelRatio(),
      height * renderer.getPixelRatio(),
      { type: THREE.HalfFloatType, samples: 4 },
    )
    composer = new EffectComposer(renderer, composerTarget)
    composer.addPass(new RenderPass(scene, camera))
    outlinePass = new ShaderPass(OUTLINE_SHADER)
    if (!new URLSearchParams(window.location.search).has('noOutline'))
      composer.addPass(outlinePass)
    // The halo is a ring of light, and a ring of geometry with a bright
    // colour on it is still a ring of geometry.  What makes it read as
    // light is the light spilling off it, and that is what this pass is
    // for.
    //
    // The threshold is the whole of it.  The body is a near-white shell
    // lit by a strong key, and it sits well above white in the linear
    // buffer the composer keeps, so a threshold low enough to catch the
    // halo also catches the body -- and a character that glows all over
    // is a character made of frosted glass, which is the one look the
    // toon shader exists to avoid.  The halo is pushed well past the
    // body's own brightness, and the threshold is set between the two, so
    // only the halo and the cores of the eyes spill.
    bloomPass = new UnrealBloomPass(
      new THREE.Vector2(width, height),
      BLOOM_STRENGTH,
      BLOOM_RADIUS,
      BLOOM_THRESHOLD,
    )
    composer.addPass(bloomPass)
    composer.addPass(new OutputPass())

    // `facing: 'authored'` keeps the model's own orientation. A VRM 1.0
    // asset faces +Z by spec, which is where this camera is, and leaving the
    // model where it was authored also keeps the look-at rest rotation and
    // the live head rotation in the same frame -- otherwise the eyes aim
    // somewhere other than where they are pointing.
    const loaded = await loadVrm(props.src, { lookAt: true, facing: 'authored' })
    if (token !== loadToken || !loaded || !actor)
      return
    vrm = loaded._vrm
    vrmGroup = loaded._vrmGroup
    // The clips are plain node-TRS tracks that drive the *raw* skeleton
    // bones, which is what the mesh is actually skinned to.  three-vrm's
    // humanoid rig would otherwise copy the normalized rig back onto the
    // raw bones every frame; the normalized rig only receives poses from
    // VRM Animation (.vrma) tracks, so that copy resets every animated
    // bone to its rest rotation and the character stands frozen.  Turning
    // the copy off keeps the mixer output.  Look-at is unaffected: the
    // applier writes the eye bones directly, every frame.
    if (vrm.humanoid)
      vrm.humanoid.autoUpdateHumanBones = false
    prepareModel(vrmGroup)
    actor.add(vrmGroup)
    animatedModel = vrmGroup
    fitActor(vrmGroup)
    introStart = performance.now()
    // The rest pose has to be read before the mixer starts writing to the
    // bones, because the living layer measures its motion against the
    // frame the character was built in.
    vrmGroup.updateMatrixWorld(true)
    collectLifeBones(vrmGroup)
    // The same rest pose is what the authored idle is retargeted onto.
    // The idle says how far a bone travels in the world; this rig says
    // where the bone sits and which way it points, and the two together
    // are what turn the source's movement into a movement this character
    // can make.  Captured now, because once the mixer starts, the rest
    // pose is gone.
    authoredRest = captureAuthoredRest(vrm, AUTHORED_BONES)
    // Dev-only handle so the browser console (and the visual QA capture
    // script) can inspect the live rig without rebuilding the model offline.
    if (import.meta.env.DEV) {
      const debug = {
        vrm,
        frames: () => frameCount,
        // How many small movements the head has made since it was
        // loaded.  A head that makes none is a rock and a head that
        // makes them all the time is a toy, and the rate says which.
        gestures: () => headGestureCount,
        clip: () => activeAction?.getClip().name ?? null,
        clipTime: () => activeAction?.time ?? null,
        // The authored idle runs on its own clock, underneath whatever
        // the state is doing, so a capture has to be able to ask where
        // in the idle the character currently is.
        authoredTime: () => authoredAction?.time ?? null,
        authoredDuration: () => authoredAction?.getClip().duration ?? null,
        playing: () => Boolean(activeAction?.isRunning()),
        weight: () => activeAction?.getEffectiveWeight() ?? null,
        mixerTime: () => mixer?.time ?? null,
        actionCount: () => actionMap.size,
        // Park the clip on an exact frame.  `mixer.setTime` is the only
        // reliable way to do this: it rewinds every action and then
        // re-evaluates the tracks at the requested time, so the pose does
        // not depend on how many frames the renderer drew beforehand.
        seek: (time: number) => {
          if (!mixer || !activeAction)
            return null
          activeAction.reset()
          mixer.setTime(time)
          return activeAction.getClip().duration
        },
        // Same, but for a named clip and without the cross-fade.  A fading
        // action blends two clips together, so a screenshot taken while the
        // fade is still running shows a pose that exists in neither clip.
        snap: (clipName: string, time: number) => {
          const action = actionMap.get(clipName)
          if (!action || !mixer)
            return null
          for (const other of actionMap.values()) {
            if (other !== action)
              other.stop()
          }
          action.reset()
          action.setLoop(THREE.LoopRepeat, Infinity)
          action.setEffectiveWeight(1)
          action.play()
          activeAction = action
          mixer.setTime(time)
          return action.getClip().duration
        },
        freeze: (value: boolean) => {
          poseFrozen = value
        },
        // Fire one of the authored gestures on demand, so the visual QA
        // harness can look at a wave without waiting for the scheduler to
        // decide that it is time.
        oneShot: (name: string) => {
          if (!actionMap.has(name))
            return false
          playOneShot(name)
          return true
        },
        oneShotPlaying: () => oneShotPlaying,
        // Run the character's clock faster than the wall clock, so a
        // capture in a slow browser can be asked for a minute of the
        // character's time instead of the three seconds it managed to
        // draw.  One is what the page runs at.
        motionTime: () => lifeClock,
        timeScale: (value: number) => {
          lifeTimeScale = Math.max(0.1, Math.min(60, value))
          return lifeTimeScale
        },
        duration: () => activeAction?.getClip().duration ?? null,
        // Live handles on the render stack, so the visual QA harness can
        // A/B the material and the outline pass without rebuilding the
        // model.  Getters rather than values, because the scene is created
        // after the debug object is built.
        composer: () => composer,
        outlinePass: () => outlinePass,
        bloomPass: () => bloomPass,
        renderer: () => renderer,
        scene: () => scene,
        camera: () => camera,
        // The shadow settings of one light, so the visual QA harness can
        // sweep them against the running model.  Self-shadowing on a
        // one-layer shell is where acne comes from, and it is a number
        // rather than a rebuild.
        setShadow: (name: string, props: Record<string, number | boolean | number[]>) => {
          const light = scene?.getObjectByName(name) as THREE.DirectionalLight | undefined
          if (!light?.shadow)
            return 'missing'
          if (typeof props.bias === 'number')
            light.shadow.bias = props.bias
          if (typeof props.normalBias === 'number')
            light.shadow.normalBias = props.normalBias
          if (typeof props.radius === 'number')
            light.shadow.radius = props.radius
          if (typeof props.mapSize === 'number') {
            light.shadow.mapSize.set(props.mapSize as number, props.mapSize as number)
            light.shadow.map?.dispose()
            light.shadow.map = null
          }
          if (Array.isArray(props.frustum)) {
            const box = props.frustum
            light.shadow.camera.left = box[0]
            light.shadow.camera.right = box[1]
            light.shadow.camera.top = box[2]
            light.shadow.camera.bottom = box[3]
            light.shadow.camera.near = box[4]
            light.shadow.camera.far = box[5]
            light.shadow.camera.updateProjectionMatrix()
          }
          if (props.cast !== undefined)
            light.castShadow = props.cast as boolean
          if (props.receive !== undefined) {
            const receive = props.receive as boolean
            scene?.traverse((object) => {
              const mesh = object as THREE.Mesh
              if (!mesh.isMesh)
                return
              // The ground is a shadow catcher of its own and keeps
              // receiving whatever the character casts on it; only the
              // character itself is switched in and out of receiving.
              const material = mesh.material as THREE.Material & { isMToonMaterial?: boolean }
              const isCharacter = Array.isArray(mesh.material)
                ? mesh.material.some(item => (item as THREE.Material & { isMToonMaterial?: boolean }).isMToonMaterial)
                : material?.isMToonMaterial
              if (isCharacter)
                mesh.receiveShadow = receive
            })
          }
          if (props.shadowSide !== undefined) {
            const side = props.shadowSide as THREE.Side
            scene?.traverse((object) => {
              const mesh = object as THREE.Mesh
              if (!mesh.isMesh)
                return
              for (const item of (Array.isArray(mesh.material) ? mesh.material : [mesh.material]) as (THREE.Material & { shadowSide?: THREE.Side })[])
                item.shadowSide = side
            })
          }
          return 'ok'
        },
        // The namespace itself, so a probe can build a plain material and
        // separate what the shader does from what the geometry does.
        three: THREE,
        // Single sided is what keeps the inside of the shell out of the
        // picture, but it also hides any surface that was wound the wrong
        // way round, and those read as holes that are not there.  Flipping
        // every material to double sided tells the two apart on the live
        // model: a hole stays a hole, a mis-wound patch fills in.
        setSide: (value: THREE.Side) => {
          let touched = 0
          scene?.traverse((object) => {
            const material = (object as THREE.Mesh).material
            if (!material)
              return
            for (const item of Array.isArray(material) ? material : [material]) {
              item.side = value
              item.needsUpdate = true
              touched += 1
            }
          })
          return touched
        },
        // One uniform on every material that has it, so the visual QA
        // harness can sweep a MToon parameter against the running model
        // without rebuilding anything.  Colours arrive as three numbers.
        setUniform: (name: string, value: number | number[]) => {
          let touched = 0
          scene?.traverse((object) => {
            const material = (object as THREE.Mesh).material
            if (!material)
              return
            for (const item of Array.isArray(material) ? material : [material]) {
              const uniforms = (item as THREE.MeshStandardMaterial).userData?.shader?.uniforms ?? (item as unknown as {
                uniforms?: Record<string, { value: unknown }>
              }).uniforms
              const uniform = uniforms?.[name]
              if (!uniform)
                continue
              if (Array.isArray(value))
                uniform.value?.setRGB?.(value[0], value[1], value[2])
              else
                uniform.value = value
              touched += 1
            }
          })
          return touched
        },
        // One uniform, but only on the materials named.  `setUniform`
        // reaches every material in the scene, which is the wrong scope
        // for the halo: it is the one object on the character that is a
        // light source rather than a surface, and it has to be judged
        // against the body it is floating over.
        setUniformOn: (names: string[], name: string, value: number | number[]) => {
          let touched = 0
          scene?.traverse((object) => {
            if (!(object instanceof THREE.Mesh))
              return
            if (!names.includes(object.name))
              return
            const material = object.material
            for (const item of Array.isArray(material) ? material : [material]) {
              const uniforms = (item as THREE.MeshStandardMaterial).userData?.shader?.uniforms ?? (item as unknown as {
                uniforms?: Record<string, { value: unknown }>
              }).uniforms
              const uniform = uniforms?.[name]
              if (!uniform)
                continue
              if (Array.isArray(value))
                uniform.value?.setRGB?.(value[0], value[1], value[2])
              else
                uniform.value = value
              touched += 1
            }
          })
          return touched
        },
        // One property on the materials named in `names`, so the glow of
        // the halo and of the eyes can be judged against the body without
        // rebuilding the asset.  The halo is a ring of light: whether it
        // reads as light or as painted plastic is decided by three numbers
        // (its own colour, how much it emits, and what the stage's
        // exposure does to the result), and each of them is worth trying
        // on its own.
        setMaterial: (names: string[], property: string, value: number) => {
          let touched = 0
          scene?.traverse((object) => {
            if (!(object instanceof THREE.Mesh))
              return
            if (!names.includes(object.name))
              return
            const material = object.material
            for (const item of Array.isArray(material) ? material : [material]) {
              if (!item)
                continue
              const record = item as unknown as Record<string, unknown>
              if (property === 'emissiveIntensity')
                record.emissiveIntensity = value
              else
                record[property] = value
              touched += 1
            }
          })
          return touched
        },
        // The colour of a material's own emission, as three numbers, so the
        // halo can be taken from a pale blue towards the saturated cyan of
        // the design without a rebuild.
        setEmissive: (names: string[], colour: number[]) => {
          let touched = 0
          scene?.traverse((object) => {
            if (!(object instanceof THREE.Mesh))
              return
            if (!names.includes(object.name))
              return
            const material = object.material
            for (const item of Array.isArray(material) ? material : [material]) {
              if (!item)
                continue
              const emission = (item as unknown as { emissive?: THREE.Color }).emissive
              emission?.setRGB(colour[0], colour[1], colour[2])
              touched += 1
            }
          })
          return touched
        },
        // The live layer's own numbers, so the halo and the rest of the
        // rig can be measured while they are moving.
        life: () => lifeBones.map(bone => ({
          bone: bone.node.name,
          local: bone.node.quaternion.toArray().map(v => +v.toFixed(4)),
          parentWorld: bone.node.parent
            ? chainWorldQuaternion(bone.node.parent, new THREE.Quaternion()).toArray().map(v => +v.toFixed(4))
            : [],
          restParent: bone.restParent.toArray().map(v => +v.toFixed(4)),
        })),
      }
      ;(window as unknown as Record<string, unknown>).__yxzDebug = debug
      ;(window as unknown as Record<string, unknown>).__yxzVrm = vrm
    }
    emote = useVRMEmote(vrm)
    if (loaded.animations.length > 0) {
      // The clips are plain node-TRS tracks exported alongside the rig, so a
      // stock AnimationMixer drives them without humanoid conversion.
      mixer = new THREE.AnimationMixer(vrm.scene)
      for (const clip of loaded.animations) {
        // The body belongs to the authored idle, and the wings and the
        // ring belong to the behaviour layer.  The clip keeps the head
        // and the arms -- the parts of the character that are hers --
        // and hands the rest over.
        releaseAuthoredBones(clip)
        // Take the visible loop out of the clip before the mixer ever sees
        // it.  The keys are edited in place, so this has to happen before
        // the action is created from the clip.
        const keep = CLIP_CALM[clip.name]
        if (keep && calmEnabled)
          calmClipMotion(clip, keep)
      }
      // The standing states hold the same arms, so that a change of
      // state is not a movement of the hands.
      shareHeldPose(loaded.animations)
      for (const clip of loaded.animations) {
        const keep = CLIP_CALM[clip.name]
        clipStillBones.set(clip.name, constantRotationBones(clip))
        clipOwnedBones.set(
          clip.name,
          new Set([
            ...Object.entries(keep ?? {})
              .filter(([, factor]) => factor === 0)
              .map(([bone]) => bone),
            // The wings and the ring are not in the clip at all any more,
            // so nothing else will write them: the behaviour layer has to
            // own them outright, or its own small motion would pile up
            // on itself frame after frame.
            ...BEHAVIOUR_BONES,
          ]),
        )
        actionMap.set(clip.name, mixer.clipAction(clip))
      }
      // The idle itself.
      //
      // It is a second action rather than a track inside the state clips,
      // and that is the point: the idle's clock runs on through every
      // state change and every gesture, so the weight shift the character
      // is standing in never jumps when she starts speaking.  Its own
      // action also keeps it out of the state clips' cross-fade, which
      // would otherwise average the two poses into a smear.
      if (authoredRest) {
        const authoredClip = buildAuthoredIdleClip(
          decodeAuthoredIdle(authoredIdlePayload),
          vrm,
          authoredRest,
          // The head is solved against the gaze target a few lines below,
          // and the solver works in world space: it decides where the head
          // has to be and then asks the neck's live rotation what the head
          // bone has to do to get there.  A clip writing the head as well
          // would be fighting that every frame, and the head would end up
          // as the average of two answers.
          { skip: ['head'] },
        )
        if (authoredClip) {
          authoredAction = mixer.clipAction(authoredClip)
          authoredAction.setLoop(THREE.LoopRepeat, Infinity)
          authoredAction.play()
        }
      }
      // `AnimationAction` has no listener of its own; the mixer reports
      // `finished` and names the action.  An authored gesture goes back to
      // the state clip when it runs out, and the celebration falls back to
      // idle, otherwise the character freezes on its last pose for the rest
      // of the session.
      mixer.addEventListener('finished', (event) => {
        if (event.action !== activeAction
          || activeAction?.loop !== THREE.LoopOnce) {
          return
        }
        if (oneShotPlaying) {
          // The gesture has run to its end.  Back to what she was doing.
          selectAction(props.status)
          return
        }
        if (props.status === 'success')
          selectAction('idle')
      })
      selectAction(props.status)
      // The first authored gesture comes reasonably early, so that a
      // visitor who opens the page sees the figure move on its own rather
      // than assuming it is a still render.
      oneShotNextAt = 10 + Math.random() * 8
    }
    if (token !== loadToken)
      return
    emote.setEmotion(emotionForStatus(props.status))
    componentState.value = 'mounted'

    motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    reducedMotion = motionQuery.matches
    motionListener = (event) => {
      reducedMotion = event.matches
    }
    motionQuery.addEventListener('change', motionListener)
    resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(canvasContainer.value)
    resize()
    animationFrame = requestAnimationFrame(animate)
  }
  catch (error) {
    componentState.value = 'pending'
    emit('error', error)
    console.error('Failed to initialize 宜小智 high-fidelity scene', error)
  }
})

watch(() => props.status, (status) => {
  selectAction(status)
  emote?.setEmotion(emotionForStatus(status))
})

onUnmounted(() => {
  loadToken++
  cancelAnimationFrame(animationFrame)
  resizeObserver?.disconnect()
  if (motionQuery && motionListener)
    motionQuery.removeEventListener('change', motionListener)
  composer?.dispose()
  composer = undefined
  outlinePass = undefined
  renderer?.dispose()
  renderer?.domElement.remove()
  actionMap.clear()
  emote?.dispose()
  mixer?.stopAllAction()
  mixer = undefined
  authoredAction = undefined
  authoredRest = undefined
  emote = undefined
  activeAction = undefined
  lifeBones = []
  lifeClock = 0
  lifeMove = null
  lifeHistory.length = 0
  lifeBoneIndex.clear()
  lifeMoveDeg = new Float32Array(0)
  lifeGazeStrength = 0
  lifeHeadNode.current = undefined
  lifeNextAt = 4.5
  lifeBurstLeft = 0
  resetMotion()
  attention.yaw = 0
  attention.pitch = 0
  attention.roll = 0
  attentionFrom.yaw = 0
  attentionFrom.pitch = 0
  attentionFrom.roll = 0
  attentionTo.yaw = 0
  attentionTo.pitch = 0
  attentionTo.roll = 0
  attentionNow.yaw = 0
  attentionNow.pitch = 0
  attentionNow.roll = 0
  attentionStart = -1
  attentionNextAt = 3.6
  gazeNextWanderAt = 0
  gazeNextSaccadeAt = 0.5
  gazeMoveStart = -10
  blinkTime = 0
  blinkStart = -1
  blinkQueue = 0
  blinkNextAt = 2
  oneShotNextAt = 0
  oneShotPlaying = ''
  mouthEnvelope = 0
  visemeClock = 0
  visemeIndex = 0
  // three-vrm has no `VRM.dispose()`; `deepDispose` is the supported teardown
  // and it also releases the geometry, materials and textures it allocated.
  if (vrm)
    VRMUtils.deepDispose(vrm.scene)
  vrm = undefined
  vrmGroup = undefined
  animatedModel = undefined
  baselineWorldSize.set(0, 0, 0)
  lastBoundsCheckAt = 0
  motionGuardTriggered = false
  scene?.traverse((object) => {
    if (!(object instanceof THREE.Mesh))
      return
    object.geometry.dispose()
    const materials = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of materials)
      material.dispose()
  })
})
</script>

<template>
  <div class="yxz-real-model-scene" :data-status="props.status" aria-label="宜小智高质量动态 3D 形象">
    <div class="yxz-real-model-bubble" role="status" aria-live="polite">
      <span class="yxz-real-model-dot" />
      <span>{{ activeLabel }}</span>
      <span v-if="isSpeaking || props.status === 'thinking' || props.status === 'processing'" class="yxz-real-model-voice-dots" :aria-label="isSpeaking ? '语音播放中' : '状态处理中'">
        <i v-for="index in 3" :key="index" :style="{ animationDelay: `${(index - 1) * 0.12}s` }" />
      </span>
    </div>
    <div ref="canvasContainer" class="yxz-real-model-canvas" />
  </div>
</template>

<style scoped>
.yxz-real-model-scene {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.yxz-real-model-canvas,
.yxz-real-model-canvas :deep(canvas) {
  width: 100%;
  height: 100%;
}

.yxz-real-model-canvas :deep(canvas) {
  display: block;
}

.yxz-real-model-bubble {
  position: absolute;
  top: 4%;
  left: 50%;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: .5rem;
  max-width: calc(100% - 2rem);
  padding: .5rem .85rem;
  border: 1px solid rgba(27, 111, 177, .22);
  border-radius: .7rem;
  background: rgba(255, 255, 255, .9);
  color: #15547c;
  box-shadow: 0 6px 20px rgba(27, 111, 177, .12);
  font-size: .82rem;
  transform: translateX(-50%);
  white-space: normal;
  overflow-wrap: anywhere;
}

.yxz-real-model-dot {
  flex-shrink: 0;
  width: .5rem;
  height: .5rem;
  border-radius: 50%;
  background: #18a8e0;
  box-shadow: 0 0 0 4px rgba(24, 168, 224, .12);
}

.yxz-real-model-scene[data-status="thinking"] .yxz-real-model-dot,
.yxz-real-model-scene[data-status="processing"] .yxz-real-model-dot {
  background: #7c72ff;
  box-shadow: 0 0 0 4px rgba(124, 114, 255, .14);
}

.yxz-real-model-scene[data-status="speaking"] .yxz-real-model-dot {
  background: #18b8a4;
  box-shadow: 0 0 0 4px rgba(24, 184, 164, .14);
}

.yxz-real-model-scene[data-status="success"] .yxz-real-model-dot {
  background: #2bb673;
  box-shadow: 0 0 0 4px rgba(43, 182, 115, .14);
}

.yxz-real-model-voice-dots {
  display: inline-flex;
  align-items: center;
  gap: .18rem;
  height: 1rem;
  margin-left: .15rem;
}

.yxz-real-model-voice-dots i {
  width: .18rem;
  height: .38rem;
  border-radius: 999px;
  background: #18a8e0;
  animation: yxz-voice-dot 0.7s ease-in-out infinite alternate;
}

@keyframes yxz-voice-dot {
  from { transform: scaleY(.55); opacity: .52; }
  to { transform: scaleY(1.35); opacity: 1; }
}
</style>
