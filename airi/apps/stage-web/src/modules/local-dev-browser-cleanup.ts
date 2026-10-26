const DEV_BROWSER_CLEANUP_REVISION = '2026-04-08-dev-browser-cleanup-v1'
const DEV_BROWSER_CLEANUP_KEY = 'airi/dev-browser-cleanup/revision'

function isLocalDevBrowser() {
  if (typeof window === 'undefined')
    return false

  return import.meta.env.DEV
    && ['localhost', '127.0.0.1'].includes(window.location.hostname)
}

async function unregisterServiceWorkers() {
  if (!('serviceWorker' in navigator))
    return

  const registrations = await navigator.serviceWorker.getRegistrations()
  await Promise.allSettled(registrations.map(registration => registration.unregister()))
}

async function clearBrowserCaches() {
  if (!('caches' in globalThis))
    return

  const keys = await caches.keys()
  await Promise.allSettled(keys.map(key => caches.delete(key)))
}

export async function cleanupLocalDevBrowserState() {
  if (!isLocalDevBrowser())
    return

  if (localStorage.getItem(DEV_BROWSER_CLEANUP_KEY) === DEV_BROWSER_CLEANUP_REVISION)
    return

  try {
    await unregisterServiceWorkers()
    await clearBrowserCaches()
  }
  catch (error) {
    console.warn('[airi] Failed to cleanup dev browser state.', error)
  }
  finally {
    localStorage.setItem(DEV_BROWSER_CLEANUP_KEY, DEV_BROWSER_CLEANUP_REVISION)
  }
}
