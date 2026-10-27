# Current Workbench Flow to API Map

| User action | Frontend entry point | API / local behavior | Failure and data boundary |
|---|---|---|---|
| Check app status | `frontend/app.js` initial health check | `GET /api/health`, `GET /api/scenes/config` | Health failure leaves the browser in a connecting state; no generation is submitted automatically. |
| Generate previews | `startPreview()` | `POST /api/previews_v2` (thinking) or `POST /api/previews`; polls `GET /api/progress/{sid}` and reads `GET /api/session/{sid}/result` | Errors are shown to the user; generation stores files under the returned session. |
| Regenerate previews | `#btn-redo` then `startPreview()` | Same preview endpoints with a new session ID | Existing session artifacts are not overwritten. |
| Select a preview | `renderPreviews()` click handler | Client-side selection by preview index | Selection is sent as `image_index` to the selected 3D endpoint. |
| Generate a 3D model | `generate3D()` | `POST /api/3d_cartoon`, `/api/3d_tripo`, `/api/3d_multi`, `/api/3d_v2`, or `/api/3d_hy` | All routes keep their existing request schemas; generated assets are session-scoped. |
| Open the local example | `startDemoExperience()` | `GET /api/demo`, then `GET /api/data/{sid}/model/mesh.glb` | Demo discovery is local-only; missing demos produce an explicit error. |
| Inspect a model | `initThree()` or `frontend/viewer.html` | `GET /api/data/{sid}/model/mesh.glb` | GLTF load errors are surfaced in the viewer status. |
| Save or restore a work | `saveProject()`, `restoreProject()` | Browser `localStorage` key `cartoon-print-projects` | Currently saves name, session/model references, and editable primitives only; it is limited to 20 entries. |
| Export a model | `downloadModel(fmt)` | `GET /api/export/{sid}/{stl|obj|glb}` | Currently serves the original session mesh, not the browser-only editable primitives. |
| Run print preflight | `refreshPrintability(sid)` | `GET /api/printability/{sid}` | Returns mesh checks, faces, extents, and warnings; an unavailable check falls back to a generic reminder. |
| Open in Bambu Studio | `printModel()` | `POST /api/print` | Hands an existing STL to the desktop launcher; the application must not start slicing or printing. |
| Discover or open desktop tools | Backend-only integration routes | `GET /api/software/detect`, `POST /api/software/open` | Opening is explicit; only existing files in the application data root are accepted. |
| Enter real-scene mode | `openSceneMode()` | `GET /api/scenes/config`, then scene upload/status/submit/asset endpoints | Scene records and Gaussian Splat assets are stored separately from printable model sessions. |

## Local Three.js Runtime

The main workbench and standalone viewer resolve `three` and `three/addons/` to `frontend/vendor/three/`. This keeps their module graph on the local app server and makes model viewing independent of browser access to a CDN.
