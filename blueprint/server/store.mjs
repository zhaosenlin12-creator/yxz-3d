// store.mjs - 数据层 + 认证 + 工具
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import crypto from "node:crypto";

const __dir = dirname(fileURLToPath(import.meta.url));
const DATA = join(__dir, "data");
mkdirSync(DATA, { recursive: true });
export const USERS_FILE = join(DATA, "users.json");
export const PROJECTS_FILE = join(DATA, "projects.json");
export const PROVIDERS_FILE = join(DATA, "providers.json");
export const T3D_FILE = join(DATA, "3dcfgs.json");
export const IMG_FILE = join(DATA, "imgcfgs.json");
export const SECRET = "local-blueprint-secret";

const readJson = (f, def) => (existsSync(f) ? JSON.parse(readFileSync(f, "utf8")) : def);
const writeJson = (f, o) => writeFileSync(f, JSON.stringify(o, null, 2), "utf8");
export const users = () => readJson(USERS_FILE, []);
export const saveUsers = (u) => writeJson(USERS_FILE, u);
export const projects = () => readJson(PROJECTS_FILE, []);
export const saveProjects = (p) => writeJson(PROJECTS_FILE, p);
export const userCfgs = () => readJson(PROVIDERS_FILE, {});
export const saveUserCfgs = (c) => writeJson(PROVIDERS_FILE, c);
export const t3dCfgs = () => readJson(T3D_FILE, {});
export const saveT3dCfgs = (c) => writeJson(T3D_FILE, c);
export const imgCfgs = () => readJson(IMG_FILE, {});
export const saveImgCfgs = (c) => writeJson(IMG_FILE, c);

export const sha = (s) => crypto.createHash("sha256").update(String(s)).digest("hex");
export const uuid = () => crypto.randomUUID();
export const now = () => new Date().toISOString();
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function makeToken(user) {
  const nowSec = Math.floor(Date.now() / 1000);
  const payload = { sub: user.id, email: user.email, aud: "authenticated", role: "authenticated", iat: nowSec, exp: nowSec + 3600 * 24 * 7 };
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const h = b64({ alg: "HS256", typ: "JWT" });
  return `${h}.${b64(payload)}.${crypto.createHmac("sha256", SECRET).update(`${h}.${b64(payload)}`).digest("base64url")}`;
}
export function parseToken(t) {
  try {
    const p = JSON.parse(Buffer.from(t.split(".")[1], "base64url").toString());
    return p.sub ? p : null;
  } catch { return null; }
}
export function gotrueUser(u) {
  return {
    id: u.id, aud: "authenticated", role: "authenticated", email: u.email,
    email_confirmed_at: u.createdAt, phone: "", confirmed_at: u.createdAt,
    last_sign_in_at: u.createdAt, app_metadata: { provider: "email", providers: ["email"] },
    user_metadata: {}, identities: [{ id: u.id, user_id: u.id, identity_data: { sub: u.id, email: u.email }, provider: "email", created_at: u.createdAt, last_sign_in_at: u.createdAt, updated_at: u.createdAt }],
    created_at: u.createdAt, updated_at: u.createdAt,
  };
}
export function session(u) {
  return { access_token: makeToken(u), token_type: "bearer", expires_in: 604800, expires_at: Math.floor(Date.now() / 1000) + 604800, refresh_token: makeToken(u), user: gotrueUser(u) };
}
export function findUserByToken(req) {
  const h = req.headers.authorization || "";
  const t = h.startsWith("Bearer ") ? h.slice(7) : null;
  if (!t) return null;
  const p = parseToken(t);
  if (!p) return null;
  return users().find((u) => u.id === p.sub) || null;
}
export function requireUser(req, res) {
  const u = findUserByToken(req);
  if (!u) { res.statusCode = 401; res.end(JSON.stringify({ error: "Unauthorized", msg: "请先登录" })); return null; }
  return u;
}
export function readBody(req) {
  return new Promise((resolve) => {
    let s = "";
    req.on("data", (d) => { s += d; if (s.length > 50e6) req.destroy(); });
    req.on("end", () => { try { resolve(s ? JSON.parse(s) : {}); } catch { resolve({ _raw: s }); } });
    req.on("error", () => resolve({}));
  });
}
export function getProject(id) { return projects().find((p) => p.id === id) || null; }
export function saveProject(p) {
  const list = projects();
  const i = list.findIndex((x) => x.id === p.id);
  if (i >= 0) list[i] = p; else list.push(p);
  saveProjects(list);
}
export function syncUser(u) {
  const list = users();
  const i = list.findIndex((x) => x.id === u.id);
  if (i >= 0) list[i] = u;
  saveUsers(list);
}
export function emptyChat() { return { turns: [], enabled: true, revision: 0, version: 1, historyEpoch: 1, activity: false, pollWhenIdle: true, images: [] }; }
export function newProject(userId, doc) {
  return {
    id: uuid(), userId, projectName: doc.projectName || "未命名项目", projectDescription: doc.projectDescription || "",
    nodeCount: Array.isArray(doc.nodes) ? doc.nodes.length : 0, partsCount: Array.isArray(doc.parts) ? doc.parts.length : 0,
    version: 1, historyEpoch: 1, starCount: 0, published: false,
    createdAt: now(), updatedAt: now(), turns: [], chat: emptyChat(), data: doc,
  };
}
export function docFromBody(body) {
  const docKeys = ["projectName", "projectDescription", "originalPrompt", "nodes", "wiring", "electricalConnections", "parts", "mechanical", "mechanicalConnections", "assembly", "instructionSteps", "instructionPreamble", "notes", "userImages", "renderPosition", "visualSnaps"];
  let d = {};
  if (body.data && typeof body.data === "object") d = { ...body.data };
  else if (body.project_data && typeof body.project_data === "object") d = { ...body.project_data };
  for (const k of docKeys) if (body[k] !== undefined) d[k] = body[k];
  return d;
}
export const MIME = {
  ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript", ".mjs": "application/javascript",
  ".json": "application/json", ".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml", ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg", ".woff2": "font/woff2", ".woff": "font/woff", ".otf": "font/otf", ".ttf": "font/ttf",
  ".ico": "image/x-icon", ".txt": "text/plain", ".zip": "application/zip", ".wasm": "application/wasm", ".mp4": "video/mp4",
};
