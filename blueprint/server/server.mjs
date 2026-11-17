// server.mjs - Blueprint 原版本地服务入口
// 默认 127.0.0.1:9418；可用 BLUEPRINT_PORT / PORT 覆盖（便于测试和新机避端口）
//   静态：web/（原版 bundle，像素级 UI）
//   /auth/v1/*  ：自建邮箱注册/登录（免邮件验证）
//   /rest/v1/*  ：PostgREST 轻量兼容
//   /storage/v1/*：占位
//   /api/*      ：原版 server API 仿真 + SSE 生成
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, dirname, extname, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { MIME, users, saveUsers, sha, uuid, now, session, gotrueUser, findUserByToken, parseToken, projects, saveProjects } from "./store.mjs";
import { handleApi } from "./api.mjs";
import { handleCourseApi } from "./course.mjs";
import { proxyYxz, yxzAlive, YXZ_PORT } from "./yxz.mjs";
import { configSummary } from "./config.mjs";

const __dir = dirname(fileURLToPath(import.meta.url));
const WEB = join(__dir, "..", "web");
const STUDIO = join(__dir, "..", "studio");
export const PORT = Number(process.env.BLUEPRINT_PORT || process.env.PORT || 9418);

// ---------------- REST（PostgREST 轻量） ----------------
function restSelect(row, select) {
  if (!select || select === "*") return row;
  const out = {};
  for (const raw of String(select).split(",")) {
    const col = raw.trim();
    const emb = col.match(/^([a-z_]+)\(([^)]*)\)$/);
    if (emb) {
      out[emb[1]] = Array.isArray(row[emb[1]]) ? (row[emb[1]] || []).map((r) => restSelect(r, emb[2])) : (row[emb[1]] ? [restSelect(row[emb[1]], emb[2])] : []);
      continue;
    }
    const jext = col.match(/^([a-z_]+)->>([a-zA-Z_]+)$/);
    if (jext) {
      const v = row[jext[1]];
      if (v && typeof v === "object" && v[jext[2]] !== undefined) out[col] = v[jext[2]];
      continue;
    }
    if (col in row) out[col] = row[col];
  }
  return out;
}
function normalizeProjectData(d) {
  // 前端渲染要求零件有 estimatedCost（数字）、quantity、id，缺失会触发 toFixed 崩溃/渲染异常
  const fixPart = (n) => {
    if (!n || typeof n !== "object") return n;
    const cost = Number(n.estimatedCost ?? n.price ?? n.estimated_price ?? 0);
    return {
      ...n,
      id: n.id || n.name || n.partId || ("p" + Math.random().toString(36).slice(2, 8)),
      estimatedCost: Number.isFinite(cost) ? cost : 0,
      quantity: n.quantity ?? n.qty ?? 1,
      // 原版渲染要求节点 pins 为数组（a.pins.join）
      pins: Array.isArray(n.pins) ? n.pins : (n.pins == null ? null : [String(n.pins)]),
    };
  };
  if (d && Array.isArray(d.nodes)) d.nodes = d.nodes.map(fixPart);
  if (d && Array.isArray(d.parts)) d.parts = d.parts.map(fixPart);
  if (d && Array.isArray(d.instructionSteps)) {
    d.instructionSteps = d.instructionSteps.map((s, i) => {
      if (!s || typeof s !== "object") return s;
      const subSteps = Array.isArray(s.subSteps) ? s.subSteps.map((v, j) => {
        if (!v || typeof v !== "object") return { title: String(v || ""), id: "s" + (i + 1) + "." + (j + 1), partIds: [] };
        return { ...v, id: v.id || "s" + (i + 1) + "." + (j + 1), partIds: Array.isArray(v.partIds) ? v.partIds : [] };
      }) : [];
      return { ...s, id: s.id || "step" + (i + 1), tools: Array.isArray(s.tools) ? s.tools : [], subSteps };
    });
  }
  if (d && d.instructionPreamble !== undefined && d.instructionPreamble !== null) {
    const p = d.instructionPreamble;
    if (typeof p === "string") {
      d.instructionPreamble = { text: p, tools: [], assumptions: [] };
    } else if (typeof p === "object") {
      d.instructionPreamble = { ...p, tools: Array.isArray(p.tools) ? p.tools : [], assumptions: Array.isArray(p.assumptions) ? p.assumptions : [] };
    }
  }
  return d;
}
function restRow(p) {
  const d = normalizeProjectData(p.data || {});
  return {
    id: p.id,
    project_name: d.projectName || p.projectName || "未命名项目",
    project_data: d, // PostgREST 对 jsonb 列返回已解析对象；前端 SHe 直接使用（不做 JSON.parse）
    created_at: p.createdAt,
    updated_at: p.updatedAt,
    node_count: (Array.isArray(d.nodes) ? d.nodes.length : 0) || p.nodeCount || 0,
    user_id: p.userId,
    version: p.version || 1,
    history_epoch: p.chat?.historyEpoch || 1,
    cad_revision: p.cadRevision ?? null,
    active_chat_head_seq: p.chat?.activeChatHeadSeq ?? null,
    thumbnail_url: p.thumbnailUrl ?? null,
    thumbnail_data: p.thumbnailData ?? null,
    published_projects: p.published ? [{ project_id: p.id, is_active: true, star_count: p.starCount || 0, published_at: p.publishedAt || p.updatedAt }] : [],
  };
}
function restFilter(rows, url) {
  const sp = url.searchParams;
  let out = [...rows];
  for (const [k, v] of sp.entries()) {
    if (["select", "order", "limit", "offset", "range", "single", "count", "or"].includes(k)) continue;
    const m = v.match(/^(eq|neq|gt|gte|lt|lte|ilike|like)\.(.*)$/);
    if (!m) continue;
    const [_, op, val] = m;
    const valClean = val.replace(/\*/g, "").trim();
    out = out.filter((row) => {
      const rv = row[k];
      if (rv === undefined || rv === null) return false;
      switch (op) {
        case "eq": return String(rv) === val;
        case "neq": return String(rv) !== val;
        case "gt": return rv > val; case "gte": return rv >= val;
        case "lt": return rv < val; case "lte": return rv <= val;
        case "ilike": return String(rv).toLowerCase().includes(valClean.toLowerCase());
        default: return true;
      }
    });
  }
  const or = sp.get("or");
  if (or && out.length) {
    const inner = or.replace(/^\(/, "").replace(/\)$/, "");
    const parts = inner.split(",");
    out = out.filter((row) => parts.some((part) => {
      const mm = part.match(/^([a-z_]+)(->>([a-zA-Z_]+))?\.(ilike|like)\.\*(.*)\*$/);
      if (!mm) return false;
      const col = mm[1], sub = mm[3], pat = (mm[5] || "").toLowerCase();
      let val = row[col];
      if (sub && val && typeof val === "object") val = val[sub];
      return String(val || "").toLowerCase().includes(pat);
    }));
  }
  const order = sp.get("order");
  if (order) {
    const [col, dir] = order.split(".");
    out.sort((a, b) => {
      const av = a[col], bv = b[col];
      const cmp = typeof av === "string" ? String(av).localeCompare(String(bv)) : (Number(av) || 0) - (Number(bv) || 0);
      return dir === "asc" ? cmp : -cmp;
    });
  }
  const range = sp.get("range");
  if (range) {
    const [start, end] = range.split("-").map(Number);
    out = out.slice(start || 0, (end ?? start) + 1);
  } else {
    const limit = Number(sp.get("limit"));
    const offset = Number(sp.get("offset") || 0);
    if (limit) out = out.slice(offset, offset + limit);
    else if (offset) out = out.slice(offset);
  }
  return out;
}
async function handleRest(req, res, url, user) {
  const table = url.pathname.replace(/^\/rest\/v1\//, "").split("/")[0].split("?")[0];
  // single 判定：postgrest-js 的 .single() 通过 Accept: application/vnd.pgrst.object+json 请求单对象（而非 URL 参数）
  const acceptH = String(req.headers.accept || "");
  const single = url.searchParams.get("single") === "true" || acceptH.includes("vnd.pgrst.object") || acceptH.includes("application/json+single");
  const select = url.searchParams.get("select") || "*";
  res.setHeader("Content-Type", "application/json");
  if (table === "projects") {
    const rows = projects().filter((p) => !user || p.userId === user.id).map(restRow);
    const mapped = restFilter(rows, url).map((r) => restSelect(r, select));
    if (single) { if (mapped.length) res.end(JSON.stringify(mapped[0])); else { res.statusCode = 406; res.end(JSON.stringify({ message: "No rows" })); } return; }
    res.end(JSON.stringify(mapped));
    return;
  }
  if (table === "chat_messages") {
    const pidParam = url.searchParams.get("project_id");
    const pid = pidParam ? pidParam.replace(/^eq\./, "") : null;
    const p = pid ? projects().find((x) => x.id === pid) : null;
    const rows = [];
    if (p) {
      (p.turns || []).forEach((t, i) => rows.push({
        seq: i, role: t.actorId === "user" ? "user" : "assistant",
        content: t.prompt || "", is_thinking: !!t.isThinking, created_at: t.createdAt || p.updatedAt, input_image_id: t.inputImageId || null, project_id: p.id,
      }));
    }
    res.end(JSON.stringify(restFilter(rows, url).map((r) => restSelect(r, select))));
    return;
  }
  if (table === "profiles") {
    const rows = users().map((u) => ({ id: u.id, username: u.username || "", bio: u.bio || "", profile_color: u.profileColor || null, email: u.email }));
    res.end(JSON.stringify(restFilter(rows, url).map((r) => restSelect(r, select))));
    return;
  }
  if (table === "subscriptions") {
    res.end(JSON.stringify([]));
    return;
  }
  if (table === "project_members") {
    // 前端 Vqe 用 HEAD 探测项目是否共享给他人；无成员时返回 200 空数组 → isShared=false（owner 模式）
    res.end(JSON.stringify([]));
    return;
  }
  if (url.pathname.includes("/rpc/")) {
    const fn = url.pathname.split("/rpc/")[1];
    if (fn === "get_my_paid_access") { res.end(JSON.stringify({ paid_access: false })); return; }
    if (fn === "check_free_trial_eligible") { res.end(JSON.stringify({ eligible: true })); return; }
    if (fn === "get_my_project_role") {
      try {
        const b = await body(req);
        const pid = b && b.p_project_id;
        const p = pid ? projects().find((x) => x.id === pid) : null;
        const role = p && user && p.userId === user.id ? "owner" : (p ? "viewer" : "viewer");
        res.end(JSON.stringify(role));
      } catch {
        res.end(JSON.stringify("viewer"));
      }
      return;
    }
    res.end(JSON.stringify({ ok: true }));
    return;
  }
  res.statusCode = 404;
  res.end(JSON.stringify({ message: "Table not found: " + table }));
}

// ---------------- 认证 ----------------  
async function handleAuth(req, res, url, path, method) {
  if (method === "POST" && path.endsWith("/signup")) {
    const b = await body(req);
    const email = String(b.email || "").trim().toLowerCase();
    const pw = String(b.password || "");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) || pw.length < 6) {
      res.statusCode = 400;
      res.end(JSON.stringify({ error: "invalid_credentials", msg: "邮箱格式不正确或密码过短（至少 6 位）" }));
      return;
    }
    const us = users();
    if (us.some((u) => u.email === email)) {
      res.statusCode = 400;
      res.end(JSON.stringify({ error: "user_already_exists", error_description: "User already registered", message: "User already registered", msg: "User already registered", hint: "该邮箱已注册，请直接登录" }));
      return;
    }
    const nu = { id: uuid(), email, password: sha(pw), username: "", bio: "", profileColor: null, createdAt: now() };
    us.push(nu);
    saveUsers(us);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(session(nu)));
    return;
  }
  if (method === "POST" && path.includes("/token")) {
    const b = await body(req);
    const gt = url.searchParams.get("grant_type") || "password";
    if (gt === "password") {
      const email = String(b.email || "").trim().toLowerCase();
      const u = users().find((x) => x.email === email && x.password === sha(String(b.password || "")));
      if (!u) {
        res.statusCode = 400;
        res.end(JSON.stringify({ error: "invalid_grant", error_description: "Invalid login credentials", message: "Invalid login credentials", msg: "Invalid login credentials", hint: "邮箱或密码错误" }));
        return;
      }
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(session(u)));
    } else {
      // refresh_token grant：解析 refresh_token（含 sub）找回原用户，避免身份漂移到 users()[0]
      const uid = parseToken(String(b.refresh_token || ""))?.sub || null;
      const u = users().find((x) => x.id === uid) || null;
      if (!u) {
        res.statusCode = 400;
        res.end(JSON.stringify({ error: "invalid_grant", error_description: "Invalid Refresh Token", message: "Invalid Refresh Token", hint: "登录已过期，请重新登录" }));
        return;
      }
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(session(u)));
    }
    return;
  }
  if (method === "GET" && path.endsWith("/user")) {
    const u = findUserByToken(req);
    if (!u) { res.statusCode = 401; res.end(JSON.stringify({ error: "no_session" })); return; }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(gotrueUser(u)));
    return;
  }
  if (method === "POST" && path.endsWith("/logout")) { res.statusCode = 204; res.end(); return; }
  if (path.endsWith("/health")) { res.writeHead(200, { "Content-Type": "application/json" }); res.end(JSON.stringify({ status: "ok" })); return; }
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end("{}");
}
function body(req) {
  return new Promise((resolve) => {
    let s = "";
    req.on("data", (d) => { s += d; if (s.length > 50e6) req.destroy(); });
    req.on("end", () => { try { resolve(s ? JSON.parse(s) : {}); } catch { resolve({ _raw: s }); } });
    req.on("error", () => resolve({}));
  });
}

// ---------------- 静态 ----------------
// 注入埋点拦截脚本（置于 <head> 最前，先于 bundle 执行，拦截第三方统计脚本/图片/iframe 注入）
const BLOCK_SCRIPT = `<script>(function(){var B=["googletagmanager.com","google-analytics.com","doubleclick.net","posthog.com","facebook.net","redditstatic.com","reddit.com","amazon-adsystem.com","hotjar.com","clarity.ms","mixpanel.com","segment.io","criteo.com","snap.licdn.com","ads.linkedin.com"];var ap=Element.prototype.appendChild,ai=Element.prototype.insertBefore;function bad(u){return !!u&&B.some(function(d){return String(u).indexOf(d)>=0;});}Element.prototype.appendChild=function(c){if(c&&c.tagName&&bad(c.src||c.href||"")){return c;}return ap.call(this,c);};Element.prototype.insertBefore=function(c,r){if(c&&c.tagName&&bad(c.src||c.href||"")){return c;}return ai.call(this,c,r);};})();</script>`;

function serveIndex(res) {
  let html = readFileSync(join(WEB, "index.html"), "utf8");
  if (!html.includes("__bp_block__")) {
    html = html.replace("<head>", "<head>" + BLOCK_SCRIPT + "<!--__bp_block__-->");
  }
  res.writeHead(200, { "Content-Type": "text/html", "Cache-Control": "no-cache" });
  res.end(html);
}

function serveStudio(res, path) {
  let rel = path === "/studio" || path === "/studio/" ? "index.html" : path.replace(/^\/studio\//, "");
  const file = join(STUDIO, rel);
  if (existsSync(file) && normalize(file).startsWith(normalize(STUDIO))) {
    const ext = extname(file).toLowerCase();
    res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream", "Cache-Control": "no-cache" });
    res.end(readFileSync(file));
  } else {
    res.statusCode = 404;
    res.end("not found");
  }
}

function serveStatic(req, res, path) {
  let rel = path === "/" ? "index.html" : path.replace(/^\//, "");
  if (rel.startsWith("assets/")) rel = rel.replace(/^assets\//, "assets/");
  const file = join(WEB, rel);
  if (existsSync(file) && normalize(file).startsWith(normalize(WEB))) {
    if (rel === "index.html") { serveIndex(res); return; }
    const ext = extname(file).toLowerCase();
    res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream", "Cache-Control": "no-cache" });
    res.end(readFileSync(file));
  } else {
    res.statusCode = 404;
    res.end("not found");
  }
}

// ---------------- 路由 ----------------
const server = createServer(async (req, res) => {
  const url = new URL(req.url, "http://127.0.0.1:" + PORT);
  const path = decodeURIComponent(url.pathname);
  const method = req.method;
  try {
    // ---- 宜小智 3D 能力服务（单入口反代） ----
    if (path === "/yxz" || path.startsWith("/yxz/")) { proxyYxz(req, res, url); return; }

    // ---- 跨应用桥：宜小智对话里直接生成 Blueprint 智造预览 ----
    if (path === "/api/bridge/preview") {
      res.setHeader("Access-Control-Allow-Origin", "*");
      res.setHeader("Access-Control-Allow-Headers", "Content-Type");
      res.setHeader("Access-Control-Allow-Methods", "POST,OPTIONS");
      if (method === "OPTIONS") { res.writeHead(204); res.end(); return; }
      if (method !== "POST") { res.writeHead(405); res.end("method not allowed"); return; }
      const b = await body(req);
      const prompt = String(b.prompt || "").trim().slice(0, 800);
      if (!prompt) { res.writeHead(400, { "Content-Type": "application/json; charset=utf-8" }); res.end(JSON.stringify({ ok: false, error: "empty prompt" })); return; }
      try {
        const r = await fetch(`http://127.0.0.1:${YXZ_PORT}/api/previews`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt, n: Math.min(4, Math.max(1, Number(b.n) || 4)), session_id: String(b.session_id || "") }),
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j.detail || `yxz ${r.status}`);
        const previews = (j.previews || []).map((p) => ({ ...p, url: p.path && p.path.startsWith("/api/") ? "/yxz" + p.path : p.path }));
        res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
        res.end(JSON.stringify({
          ok: true,
          session_id: j.session_id,
          source: j.source,
          previews,
          studio_url: `/studio?session=${encodeURIComponent(j.session_id)}&mode=3d&n=${previews.length || 4}#3d`,
        }));
      } catch (e) {
        res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
        res.end(JSON.stringify({ ok: false, error: String(e && e.message || e) }));
      }
      return;
    }
    // ---- 智造工作台（3D 工坊 + 课程模式） ----
    if (method === "GET" && (path === "/studio" || path.startsWith("/studio/"))) { serveStudio(res, path); return; }
    if (path === "/api/studio/status" && method === "GET") {
      const r = await yxzAlive();
      res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ ok: true, yxz: { port: YXZ_PORT, alive: r.ok, health: r.data, error: r.error || null }, config: configSummary() }));
      return;
    }
    if (path.startsWith("/api/studio")) { await handleCourseApi(req, res, url, path, method); return; }
    if (method === "GET" && (path === "/" || path === "/index.html" || path === "/inject.js" || path.startsWith("/assets/") || path.startsWith("/landing/") || path.startsWith("/brand/") || path.startsWith("/fonts/") || path.startsWith("/favicons/"))) {
      serveStatic(req, res, path);
      return;
    }
    // SPA 回退：非 API 的 GET 路由一律返回 index.html（/projects /account /community /project/:id 等）
    if (method === "GET") {
      const isApi = path.startsWith("/api") || path.startsWith("/auth") || path.startsWith("/rest") || path.startsWith("/storage");
      if (!isApi) {
        serveIndex(res);
        return;
      }
    }
    if (path.startsWith("/auth/v1")) { await handleAuth(req, res, url, path, method); return; }
    if (path.startsWith("/rest/v1")) {
      // 修复：无有效 token 时不再回退到 users()[0]（会导致身份伪装、按错误 userId 过滤项目 → 404）
      // 无 token → 401；有 token → 解析真实用户
      const u = findUserByToken(req);
      if (!u) { res.statusCode = 401; res.end(JSON.stringify({ message: "Unauthorized" })); return; }
      await handleRest(req, res, url, u);
      return;
    }
    if (path.startsWith("/storage/v1")) { res.statusCode = 404; res.end("not found"); return; }
    if (path.startsWith("/api")) {
      if (/generation-runs|projects\/save|projects\/[^/]+\/chat/.test(path)) console.log(">REQ " + method + " " + path);
      await handleApi(req, res, url, path, method);
      return;
    }
    res.statusCode = 404;
    res.end("not found");
  } catch (e) {
    res.statusCode = 500;
    res.end(JSON.stringify({ error: "internal_error", msg: String(e.message || e) }));
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log("");
  console.log("==============================================");
  console.log("  Blueprint 本地复刻版（原版 UI 一比一）");
  console.log("  地址: http://127.0.0.1:" + PORT);
  console.log("  登录: 邮箱注册即登录（免邮件验证）");
  console.log("  模型: 未配置时用内置演示生成器；");
  console.log("        「账号」页可配置国内外大模型 API");
  console.log("==============================================");
});

// 进程级兜底：任何未捕获异常/拒绝只记录日志，不退出服务
process.on("uncaughtException", (e) => { console.error("[uncaughtException]", e && e.stack ? e.stack : e); });
process.on("unhandledRejection", (e) => { console.error("[unhandledRejection]", e && e.stack ? e.stack : e); });
