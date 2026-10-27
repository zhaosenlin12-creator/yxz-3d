/**
 * Web stub for @proj-airi/electron-screen-capture/renderer.
 * The real package is electron-only and may not be built in web runs;
 * stage-web never uses screen capture, so export a harmless no-op.
 */
export interface ElectronScreenCaptureStubContext {
  context: unknown
}

export function setupElectronScreenCapture(_ctx: ElectronScreenCaptureStubContext) {
  return {
    selectWithSource: async () => {
      throw new Error('Electron screen capture is unavailable in the web build')
    },
  }
}

export default setupElectronScreenCapture
