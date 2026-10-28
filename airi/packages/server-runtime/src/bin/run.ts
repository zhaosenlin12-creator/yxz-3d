#!/usr/bin/env tsx

import process, { env, exit } from 'node:process'

import { createServer } from '../server'

const server = createServer({
  port: env.PORT ? Number.parseInt(env.PORT) : 6121,
  // The runtime is the channel the chat talks over.  Visitors that open the
  // workbench from another computer on the network have to reach it, so it
  // listens on every interface unless the caller says otherwise.
  hostname: env.HOST || '0.0.0.0',
})

let stopping = false

async function shutdown() {
  if (stopping)
    return
  stopping = true
  await server.stop()
  exit(0)
}

process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)

server.start()
