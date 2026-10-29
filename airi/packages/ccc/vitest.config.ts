import { defineConfig } from 'vitest/config'

// This package ships fixtures, not unit tests.  Without its own config
// vitest walks up to the monorepo root and tries to resolve the root
// project list relative to this directory, which fails before a single
// test runs.
export default defineConfig({
  test: {
    passWithNoTests: true,
  },
})
