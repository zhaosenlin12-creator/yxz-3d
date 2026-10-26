#!/usr/bin/env node
// Auto-install pnpm so a fresh clone can `pnpm install` right after.
// This monorepo uses pnpm-specific features (catalog:, shellEmulator, patchedDependencies)
// and is NOT compatible with npm / yarn. Run this once on a new machine.
//
// Usage:
//   node scripts/setup-pnpm.mjs           # install latest pnpm
//   node scripts/setup-pnpm.mjs 10.32.1   # pin a specific version (matches packageManager in package.json)
//
// Strategy, in order, STOPPING at the first that succeeds (we never auto-run installers
// that modify your PATH or shell profile without you opting in):
//   1. corepack enable + corepack prepare pnpm@<ver> --activate
//   2. `npm install -g pnpm@<ver>` (only if corepack wasn't usable)
//
// If both fail we print manual install instructions and exit non-zero. To use the official
// installer (modifies PATH / shell profile) you must run it yourself.

import process from 'node:process'

import { spawnSync } from 'node:child_process'
import { platform } from 'node:os'

const REQUIRED_NODE = '16.13.0'
const requested = process.argv[2] || 'latest'
const isWindows = platform() === 'win32'

function compareVersion(a, b) {
  const [aMaj, aMin, aPatch] = a.split('.').map(Number)
  const [bMaj, bMin, bPatch] = b.split('.').map(Number)
  if (aMaj !== bMaj)
    return aMaj - bMaj
  if (aMin !== bMin)
    return aMin - bMin
  return aPatch - bPatch
}

function run(cmd, args) {
  // On Windows, .cmd shims (npm.cmd, corepack.cmd) require shell: true or they fail with
  // EINVAL. Use shell: true everywhere for consistent behavior; pass args as an array so the
  // shell handles them as separate tokens (avoids the worst of DEP0190 quoting concerns).
  return spawnSync(cmd, args, { stdio: 'inherit', shell: isWindows })
}

function runSilent(cmd, args) {
  return spawnSync(isWindows ? 'where' : 'which', [cmd], { encoding: 'utf8' })
}

function which(name) {
  const r = runSilent(name)
  return r.status === 0 ? r.stdout.trim().split(/\r?\n/)[0] : null
}

const nodeVersion = process.versions.node
if (compareVersion(nodeVersion, REQUIRED_NODE) < 0) {
  console.error(`[setup-pnpm] Node ${REQUIRED_NODE}+ required, you have ${nodeVersion}.`)
  console.error('[setup-pnpm] Download: https://nodejs.org/')
  process.exit(1)
}

let ok = false
const corepackPath = which('corepack')

if (corepackPath) {
  console.log(`[setup-pnpm] Found corepack at ${corepackPath}.`)
  const enable = run('corepack', ['enable'])
  if (enable.status === 0) {
    const prepare = run('corepack', ['prepare', `pnpm@${requested}`, '--activate'])
    if (prepare.status === 0)
      ok = true
  }
  else {
    console.error('[setup-pnpm] `corepack enable` failed (often: read-only global Node install dir).')
  }
}

if (!ok && (which('npm'))) {
  console.log(`[setup-pnpm] Falling back to: npm install -g pnpm@${requested}`)
  const r = run('npm', ['install', '-g', `pnpm@${requested}`])
  if (r.status === 0)
    ok = true
  else console.error('[setup-pnpm] npm install -g pnpm failed.')
}

if (!ok) {
  console.error('')
  console.error('[setup-pnpm] Auto-install failed (corepack and npm -g both unavailable or permission-denied).')
  console.error('[setup-pnpm] Pick ONE of these manual options:')
  console.error('')
  console.error('  # macOS / Linux (no sudo required, installs to ~/.local):')
  console.error('  curl -fsSL https://get.pnpm.io/install.sh | sh -')
  console.error('')
  console.error('  # Windows (PowerShell, no admin required, installs to %LOCALAPPDATA%):')
  console.error('  iwr https://get.pnpm.io/install.ps1 -useb | iex')
  console.error('')
  console.error('  # Anywhere with npm:')
  console.error('  npm install -g pnpm')
  console.error('')
  console.error('  # Or use a Node version manager: https://pnpm.io/installation')
  process.exit(1)
}

const verify = run('pnpm', ['--version'])
if (verify.status !== 0) {
  console.error('')
  console.error('[setup-pnpm] pnpm installed but is not on PATH yet. Open a new shell, or:')
  if (!isWindows)
    console.error('  export PATH="$HOME/.local/share/pnpm:$PATH"')
  else console.error('  $env:Path = "$env:USERPROFILE\\AppData\\Local\\pnpm;$env:Path"')
  process.exit(1)
}

console.log('')
console.log('[setup-pnpm] Done. Next steps:')
console.log('  pnpm install')
console.log('  pnpm -F @proj-airi/stage-web dev')
console.log('')
console.log('See SETUP.md for the full guide.')
