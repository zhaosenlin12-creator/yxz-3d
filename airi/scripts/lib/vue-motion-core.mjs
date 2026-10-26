/**
 * Lifting the YXZ motion core out of the component.
 *
 * The component keeps the whole of its idle motion in one marked
// block, and two tools need to run exactly that block outside the
 * browser: the probe that measures it and the trace that shows it.
 * Both read it the same way, so that a number and a picture always
 * describe the same motion.
 */

import { readFileSync } from 'node:fs'

/**
 * The TypeScript in the block, taken off.
 *
 * The block is written as TypeScript because the component is, and it
 * has to run as JavaScript here.  The rules are deliberately narrow:
 * anything they do not recognise is left alone, so a type they cannot
 * strip shows up as a syntax error rather than as a measurement of
 * something else.
 */
export function stripTypes(text) {
  return text
    // Interfaces and type aliases have no runtime meaning at all, and
    // they are the only TypeScript in the motion core that cannot be
    // stripped by a rule: their bodies are declarations, not values.
    .replace(/^interface\s+\w+(?:<[^>]*>)?\s*\{[\s\S]*?^\}\s*$/gm, '')
    .replace(/^type\s+\w+(?:<[^>]*>)?\s*=[^\n]*$/gm, '')
    .replace(/\s*:\s*number\b/g, '')
    // Local declarations: `const segment: PostureSegment = {`.
    .replace(/^(\s*(?:const|let)\s+\w+)\s*:\s*(\[[\w,\s[\]]*\]|[A-Za-z_][\w.[\]<>| ]*)(\s*=)/gm, '$1$3')
    // Parameter annotations: `(k, action: LifeAction)` and
    // `(status: YXZStatus)`.  Only inside the signature, which is the
    // text before the first `{`.
    .replace(/^(\s*(?:export\s+)?function\s+\w+\s*\(([^)]*)\))/gm,
      (_, signature) => signature.replace(/:\s*(\[[\w,\s[\]]*\]|[A-Za-z_][\w.[\]<>| ]*)/g, ''))
    // Arrow functions carry their annotations in the parameter list, and
    // the parameter list is not a function signature, so it needs its
    // own rule.
    .replace(/(\([^()]*\))(\s*=>)/g,
      (_, params, arrow) => params.replace(/:\s*(\[[\w,\s[\]]*\]|[A-Za-z_][\w.[\]<>| ]*)/g, '') + arrow)
}

/**
 * The motion core, as JavaScript.
 *
 * The block is taken whole.  Lifting the pieces rather than the block
 * is how a measurement stops describing the thing on screen: the
 * pieces are written to be read together, and a tool that reads them
 * apart is measuring something that does not exist.
 */
export function loadMotionCore(vuePath) {
  const source = readFileSync(vuePath, 'utf8')
  const begin = source.indexOf('>>> YXZ MOTION CORE BEGIN')
  const end = source.indexOf('<<< YXZ MOTION CORE END')
  if (begin < 0 || end < 0)
    throw new Error('the motion core block is missing')
  return stripTypes(source.slice(source.indexOf('\n', begin) + 1, end))
}
