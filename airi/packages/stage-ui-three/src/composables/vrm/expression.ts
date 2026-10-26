import type { VRMCore } from '@pixiv/three-vrm-core'

import { ref } from 'vue'

interface EmotionState {
  expression?: {
    name: string
    value: number
    duration?: number
    curve?: (t: number) => number
  }[]
  blendDuration?: number
}

export function useVRMEmote(vrm: VRMCore) {
  const currentEmotion = ref<string | null>(null)
  const isTransitioning = ref(false)
  const transitionProgress = ref(0)
  const currentExpressionValues = ref(new Map<string, number>())
  const targetExpressionValues = ref(new Map<string, number>())
  const resetTimeout = ref<number>()

  // Utility functions
  const lerp = (start: number, end: number, t: number): number => {
    return start + (end - start) * t
  }

  const easeInOutCubic = (t: number): number => {
    return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2
  }

  const clampIntensity = (value: number): number => {
    return Math.min(1, Math.max(0, value))
  }

  // `neutral`, `oh` and `think` are not VRM 1.0 preset expressions, so most
  // models simply do not define them. Resolve each requested name against the
  // model's own expression map and fall back to the nearest equivalent rather
  // than writing a value the expression manager will silently discard.
  // The literal name always wins, so models that *do* define these keep their
  // intended shapes.
  const EXPRESSION_ALIASES: Record<string, string> = {
    neutral: 'relaxed',
    oh: 'ou',
    oo: 'ou',
    think: 'relaxed',
  }

  function resolveExpressionName(name: string): string | undefined {
    const available = vrm.expressionManager?.expressionMap
    if (!available)
      return undefined
    if (name in available)
      return name
    const alias = EXPRESSION_ALIASES[name]
    return alias && alias in available ? alias : undefined
  }

  // Emotion states definition — values are the "full weight" targets;
  // actual applied weight is value × clamped intensity.
  // Using slightly lower values (0.7–0.8) for primary expressions to
  // prevent the "too raw / smiles too much" problem reported in #590.
  const emotionStates = new Map<string, EmotionState>([
    ['happy', {
      expression: [
        { name: 'happy', value: 0.7, duration: 0.3 },
        { name: 'aa', value: 0.2 },
      ],
      blendDuration: 0.4,
    }],
    ['sad', {
      expression: [
        { name: 'sad', value: 0.7 },
        { name: 'oh', value: 0.15 },
      ],
      blendDuration: 0.4,
    }],
    ['angry', {
      expression: [
        { name: 'angry', value: 0.7 },
        { name: 'ee', value: 0.3 },
      ],
      blendDuration: 0.3,
    }],
    ['surprised', {
      expression: [
        { name: 'surprised', value: 0.8 },
        { name: 'oh', value: 0.4 },
      ],
      blendDuration: 0.15,
    }],
    ['neutral', {
      expression: [
        { name: 'neutral', value: 1.0 },
      ],
      blendDuration: 0.6,
    }],
    // The resting face. `relaxed` is a VRM 1.0 preset expression, so it is
    // available on any conformant model, and it is the calm counterpart to
    // the `neutral` reset above rather than a synonym for it.
    ['relaxed', {
      expression: [
        { name: 'relaxed', value: 0.5 },
      ],
      blendDuration: 0.8,
    }],
    ['think', {
      expression: [
        { name: 'think', value: 0.7 },
      ],
      blendDuration: 0.5,
    }],
  ])

  const clearResetTimeout = () => {
    if (resetTimeout.value) {
      clearTimeout(resetTimeout.value)
      resetTimeout.value = undefined
    }
  }

  const setEmotion = (emotionName: string, intensity = 1) => {
    clearResetTimeout()

    if (!emotionStates.has(emotionName)) {
      console.warn(`Emotion ${emotionName} not found`)
      return
    }

    const emotionState = emotionStates.get(emotionName)!
    currentEmotion.value = emotionName
    isTransitioning.value = true
    transitionProgress.value = 0

    // Store current expression values as starting point BEFORE resetting,
    // so the lerp transition starts from the actual displayed values
    // instead of snapping to 0 first (fixes #590).
    currentExpressionValues.value.clear()
    targetExpressionValues.value.clear()

    const normalizedIntensity = clampIntensity(intensity)

    if (vrm.expressionManager) {
      // Capture current values for all expressions we'll be transitioning
      const expressionNames = Object.keys(vrm.expressionManager.expressionMap)
      for (const name of expressionNames) {
        const currentValue = vrm.expressionManager.getValue(name) || 0
        currentExpressionValues.value.set(name, currentValue)
        // Default target is 0 for expressions not in the target emotion
        targetExpressionValues.value.set(name, 0)
      }
    }

    // Override target values for specified expressions in the emotion state.
    // Unresolvable names are skipped: `neutral` in particular is just "every
    // expression back to zero", which the default loop below already does.
    for (const expr of emotionState.expression || []) {
      const resolved = resolveExpressionName(expr.name)
      if (resolved === undefined) {
        if (expr.name !== 'neutral')
          console.warn(`Expression "${expr.name}" is not available on this VRM; skipping it`)
        continue
      }
      targetExpressionValues.value.set(resolved, expr.value * normalizedIntensity)
    }
  }

  const setEmotionWithResetAfter = (emotionName: string, ms: number, intensity = 1) => {
    clearResetTimeout()
    setEmotion(emotionName, intensity)

    // Set timeout to reset to neutral
    resetTimeout.value = setTimeout(() => {
      setEmotion('neutral')
      resetTimeout.value = undefined
    }, ms) as unknown as number
  }

  const update = (deltaTime: number) => {
    if (!isTransitioning.value || !currentEmotion.value)
      return

    const emotionState = emotionStates.get(currentEmotion.value)!
    const blendDuration = emotionState.blendDuration || 0.3

    transitionProgress.value += deltaTime / blendDuration
    if (transitionProgress.value >= 1.0) {
      transitionProgress.value = 1.0
      isTransitioning.value = false
    }

    // Update all expressions
    for (const [exprName, targetValue] of targetExpressionValues.value) {
      const startValue = currentExpressionValues.value.get(exprName) || 0
      const currentValue = lerp(
        startValue,
        targetValue,
        easeInOutCubic(transitionProgress.value),
      )
      vrm.expressionManager?.setValue(exprName, currentValue)
    }
  }

  const addEmotionState = (emotionName: string, state: EmotionState) => {
    emotionStates.set(emotionName, state)
  }

  const removeEmotionState = (emotionName: string) => {
    emotionStates.delete(emotionName)
  }

  // Cleanup function
  const dispose = () => {
    clearResetTimeout()
  }

  return {
    currentEmotion,
    isTransitioning,
    setEmotion,
    setEmotionWithResetAfter,
    update,
    addEmotionState,
    removeEmotionState,
    dispose,
  }
}
