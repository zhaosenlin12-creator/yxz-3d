import { isStageWeb } from '@proj-airi/stage-shared'

import packageJSON from '../../package.json'

export function useBuildInfo() {
  const version = packageJSON.version ?? 'dev'
  const buildTime = new Date()

  return {
    version: isStageWeb() ? version : version,
    commit: 'dev',
    branch: 'main',
    builtOn: buildTime.toISOString(),
  }
}
