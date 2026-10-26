// Which bones each shipped clip actually drives.
//
// The living layer writes to a bone every frame.  When the mixer also
// drives that bone the two compose cleanly, but when the mixer has no
// track for it the write accumulates frame after frame and the limb
// slowly winds itself into a knot.  This lists the tracks per clip so
// that case is visible instead of theoretical.
//
// Usage:
//   node scripts/probe_yxz_clip_tracks.mjs <vrm>

import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const file = process.argv[2]
if (!file || !existsSync(file))
  throw new Error(`usage: node scripts/probe_yxz_clip_tracks.mjs <vrm>`)

const buffer = readFileSync(file)
let offset = 12
let json = null
while (offset + 8 <= buffer.length) {
  const length = buffer.readUInt32LE(offset)
  const type = buffer.readUInt32LE(offset + 4)
  const start = offset + 8
  if (type === 0x4E4F534A)
    json = JSON.parse(buffer.toString('utf8', start, start + length))
  offset = start + length + ((4 - (length % 4)) % 4)
}
if (!json)
  throw new Error('no JSON chunk')

const names = (json.nodes ?? []).map(node => node.name ?? '')
for (const animation of json.animations ?? []) {
  const bones = new Map()
  for (const track of animation.channels ?? []) {
    const target = track.target?.node
    if (target === undefined)
      continue
    const name = names[target] ?? `#${target}`
    const path = track.target?.path ?? '?'
    bones.set(name, (bones.get(name) ?? new Set()).add(path))
  }
  const list = [...bones.entries()]
    .map(([name, paths]) => `${name}(${[...paths].join(',')})`)
    .sort()
  console.log(`\n=== ${animation.name} — ${list.length} nodes`)
  for (const item of list)
    console.log(`  ${item}`)
}
