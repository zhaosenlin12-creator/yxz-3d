import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { playwright } from '@vitest/browser-playwright'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

export default defineConfig(({ mode }) => ({
  test: {
    // The transcription pipeline is exercised through the app, not through
    // unit tests here -- an empty run must not fail the build.
    passWithNoTests: true,
    projects: [
      {
        test: {
          name: 'node',
          root: dirname(fileURLToPath(import.meta.url)),
          env: loadEnv(mode, dirname(fileURLToPath(import.meta.url))),
          exclude: ['**/*.browser.{spec,test}.ts', '**/node_modules/**'],
          passWithNoTests: true,
        },
      },
      {
        test: {
          name: 'browser',
          root: dirname(fileURLToPath(import.meta.url)),
          include: ['**/*.browser.{spec,test}.ts'],
          exclude: ['**/node_modules/**'],
          passWithNoTests: true,
          browser: {
            provider: playwright(),
            enabled: true,
            // at least one instance is required
            instances: [
              { browser: 'chromium' },
            ],
          },
        },
      },
    ],
  },
}))
