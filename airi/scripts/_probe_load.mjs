import { readFileSync, readdirSync } from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { pathToFileURL } from "node:url"
const require = createRequire(import.meta.url)
let playwright
try { playwright = await import(pathToFileURL(require.resolve("playwright")).href) }
catch {
  const store = path.resolve("node_modules/.pnpm")
  const match = readdirSync(store).filter(n=>n.startsWith("playwright@")).sort().at(-1)
  playwright = await import(pathToFileURL(path.join(store, match, "node_modules","playwright","index.js")).href)
}
const root = path.join(process.env.LOCALAPPDATA, "ms-playwright")
const rev = readdirSync(root).filter(n=>n.startsWith("chromium-")).sort((a,b)=>Number.parseInt(b.slice(9),10)-Number.parseInt(a.slice(9),10))[0]
const exe = path.join(root, rev, "chrome-win64","chrome.exe")
const chromium = playwright.chromium ?? playwright.default?.chromium
const browser = await chromium.launch({executablePath: exe, args:["--use-gl=angle","--use-angle=swiftshader","--enable-unsafe-swiftshader"]})
const page = await browser.newPage({viewport:{width:1000,height:900}})
const logs=[]
page.on("console", m => logs.push("CONSOLE "+m.type()+": "+m.text()))
page.on("pageerror", e => logs.push("PAGEERROR: "+e.message))
const candidate = path.resolve(process.argv[2]||"docs/yxz-variants/r138-mouth-safe/yxz-texture.vrm")
await page.route("**/*", async (route)=>{
  const url = new URL(route.request().url())
  if (!url.pathname.endsWith("/yxz.vrm") || !["fetch","xhr"].includes(route.request().resourceType())) { await route.continue(); return }
  await route.fulfill({status:200, contentType:"model/gltf-binary", body: readFileSync(candidate)})
})
await page.goto("http://127.0.0.1:5199/yxz-avatar", {waitUntil:"domcontentloaded", timeout:120000})
await page.waitForTimeout(60000)
const state = await page.evaluate(()=>{
  const dd = document.querySelector(".readout dd")
  return { readout: dd?.textContent?.trim(), hasDebug: !!window.__yxzDebug, body: document.body.innerText.slice(0,300) }
})
console.log(JSON.stringify(state,null,1))
console.log(logs.slice(0,40).join("\n"))
await page.screenshot({path:"docs/yxz-audit/load-check.png"})
await browser.close()

