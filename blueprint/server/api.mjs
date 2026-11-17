// api.mjs - /api/* 处理器（原版 server.blueprint.io 仿真 + SSE 生成）
import { getProvider, callLLM } from "./llm.mjs";
import { generateDoc, demoDoc } from "./gen.mjs";
import { submitHunyuan3D, queryHunyuan3D } from "./tc3.mjs";
import { effectiveLlm, effectiveImage, effective3d, configSummary } from "./config.mjs";
import { users, projects, userCfgs, saveProjects, saveUserCfgs, saveUsers, getProject, saveProject, requireUser, readBody, now, sleep, uuid, emptyChat, newProject, t3dCfgs, saveT3dCfgs, imgCfgs, saveImgCfgs } from "./store.mjs";

export async function handleApi(req, res, url, path, method) {
  // 公开端点
  if (method === "GET" && path === "/api/providers") {
    const { PROVIDERS } = await import("./llm.mjs");
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ providers: PROVIDERS }));
    return;
  }
  // 公开端点（无需登录）
  if (path === "/api/features") { res.end(JSON.stringify({ proTrial: { enabled: false, days: 0 }, projectCollabSaleEnabled: false })); return; }
  if (path === "/api/capabilities") { res.end(JSON.stringify({ clearChatHistory: true })); return; }
  if (path === "/api/config-status" && method === "GET") {
    res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ ok: true, ...configSummary() }));
    return;
  }
  if (path === "/api/check-username" && method === "GET") {
    const name = (url.searchParams.get("username") || "").toLowerCase();
    const taken = users().some((u) => u.username && u.username.toLowerCase() === name) || !/^[a-z0-9_]{3,20}$/.test(name);
    res.end(JSON.stringify({ available: !taken, username: name }));
    return;
  }
  if (path === "/api/stats") {
    const list = projects();
    res.end(JSON.stringify({ projectsCreated: list.length + 300000, accountsCreated: users().length + 250000, publishedProjects: list.filter((p) => p.published).length + 15000 }));
    return;
  }
  if (path === "/api/trending") {
    const list = projects().filter((p) => p.published).slice(0, Number(url.searchParams.get("limit") || 4));
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(list.map(commItem)));
    return;
  }
  if (path === "/api/community") {
    const q = (url.searchParams.get("q") || "").trim();
    let list = projects().filter((p) => p.published);
    if (q) list = list.filter((p) => (p.data?.projectName || p.projectName).toLowerCase().includes(q.toLowerCase()) || (p.data?.projectDescription || "").toLowerCase().includes(q.toLowerCase()));
    list = list.sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
    const limit = Number(url.searchParams.get("limit") || 24);
    const offset = Number(url.searchParams.get("offset") || 0);
    const page = list.slice(offset, offset + limit);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ projects: page.map(commItem), total: list.length, hasMore: offset + limit < list.length, searchMode: "exact", discoverySnapshot: "local-v1-" + Date.now() }));
    return;
  }

  const user = requireUser(req, res);
  if (!user) return;

  if (path === "/api/check-subscription") {
    res.end(JSON.stringify({ subscriptionPlanTier: "free", subscriptionStatus: null, cancelAt: null, syncPending: false, cancellationStatus: null, accessSource: "free", accessEndsAt: null, billingReviewRequired: false, isSubscribed: false, planTier: "free" }));
    return;
  }
  if (path === "/api/billing/trial-eligibility") {
    res.end(JSON.stringify({ eligible: true, days: 7, trialAvailable: true }));
    return;
  }
  if (path === "/api/conversions/registration") { res.end(JSON.stringify({ ok: true })); return; }
  if (path === "/api/update-username" && method === "POST") {
    const b = await readBody(req);
    const name = String(b.username || "").toLowerCase();
    if (!/^[a-z0-9_]{3,20}$/.test(name) || users().some((u) => u.username && u.username.toLowerCase() === name && u.id !== user.id)) {
      res.statusCode = 400;
      res.end(JSON.stringify({ error: "invalid_username" }));
      return;
    }
    const us = users();
    const u = us.find((x) => x.id === user.id);
    if (u) { u.username = name; saveUsers(us); }
    res.end(JSON.stringify({ ok: true, username: name }));
    return;
  }
  if (path === "/api/projects" && method === "GET") {
    const scope = url.searchParams.get("scope");
    const q = (url.searchParams.get("q") || "").trim();
    const limit = Number(url.searchParams.get("limit") || 20);
    const offset = Number(url.searchParams.get("offset") || 0);
    let list = projects().filter((p) => p.userId === user.id);
    if (scope === "published") list = list.filter((p) => p.published);
    if (q) list = list.filter((p) => (p.data?.projectName || p.projectName).toLowerCase().includes(q.toLowerCase()));
    list = list.sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
    const page = list.slice(offset, offset + limit);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ projects: page.map(projectPublic), total: list.length, hasMore: offset + limit < list.length }));
    return;
  }
  if (path === "/api/projects/save" && method === "POST") {
    const b = await readBody(req);
    const { docFromBody } = await import("./store.mjs");
    const doc = docFromBody(b);
    let p = b.id ? getProject(b.id) : null;
    if (!p) {
      const { newProject } = await import("./store.mjs");
      p = newProject(user.id, doc);
    } else {
      p.data = { ...(p.data || {}), ...doc };
      p.projectName = doc.projectName || p.projectName;
      p.projectDescription = doc.projectDescription || p.projectDescription;
      p.nodeCount = Array.isArray(doc.nodes) ? doc.nodes.length : p.nodeCount;
      if (b.turns && Array.isArray(b.turns)) p.turns = b.turns;
      p.updatedAt = now();
      if (b.version) p.version = b.version;
    }
    saveProject(p);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ projectData: p.data || {}, version: p.version || 1, historyEpoch: p.chat?.historyEpoch || 1 }));
    return;
  }
  const projMatch = path.match(/^\/api\/projects\/([^/]+)(\/.*)?$/);
  if (projMatch) return handleProject(req, res, url, projMatch, method, user);

  if (path === "/api/gemini" && method === "POST") { await runGemini(req, res, user); return; }
  if (path === "/api/gemini/jobs") { res.end(JSON.stringify({ status: "noop", data: null })); return; }
  if (path.startsWith("/api/generation-runs")) { await handleGenerationRuns(req, res, url, method, user); return; }
  if (path === "/api/get-credits" && method === "POST") { res.end(JSON.stringify({ weekly_credits_remaining: 999999 })); return; }
  if (path === "/api/consume-credit" && method === "POST") { res.end(JSON.stringify({ ok: true })); return; }
  if (path === "/api/user-provider" && method === "GET") {
    const c = effectiveLlm(user.id, userCfgs()) || {};
    res.end(JSON.stringify(c));
    return;
  }
  if (path === "/api/user-provider" && method === "PUT") {
    const b = await readBody(req);
    const p = getProvider(b.provider);
    if (!p && b.provider) { res.statusCode = 400; res.end(JSON.stringify({ error: "unknown_provider" })); return; }
    const cfg = { provider: b.provider, apiKey: String(b.apiKey || ""), baseUrl: String(b.baseUrl || ""), model: String(b.model || ""), providerName: p?.name || "", updatedAt: now() };
    const all = userCfgs();
    all[user.id] = cfg;
    saveUserCfgs(all);
    res.end(JSON.stringify(cfg));
    return;
  }
  if (path === "/api/llm/test" && method === "POST") {
    const b = await readBody(req);
    try {
      const t0 = Date.now();
      await callLLM({ provider: b.provider, apiKey: b.apiKey, baseUrl: b.baseUrl, model: b.model, system: b.system || "回复OK两个字符", user: b.user || "ping", maxTokens: 16 });
      res.end(JSON.stringify({ ok: true, ms: Date.now() - t0 }));
    } catch (e) {
      res.statusCode = 400;
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
    return;
  }
  // ---------- 混元 3D 生成 ----------
  if (path === "/api/3d/cfg" && method === "GET") {
    const c = effective3d(user.id, t3dCfgs()) || {};
    res.end(JSON.stringify({ secretId: c.secretId ? "已配置" : "", secretKey: c.secretKey ? "已配置" : "", region: c.region || "", source: c.source || "user" }));
    return;
  }
  if (path === "/api/3d/cfg" && method === "PUT") {
    const b = await readBody(req);
    if (!b.secretId || !b.secretKey) { res.statusCode = 400; res.end(JSON.stringify({ error: "secretId 与 secretKey 均必填" })); return; }
    const all = t3dCfgs();
    all[user.id] = { secretId: String(b.secretId).trim(), secretKey: String(b.secretKey).trim(), region: String(b.region || "ap-guangzhou").trim(), updatedAt: now() };
    saveT3dCfgs(all);
    res.end(JSON.stringify({ ok: true }));
    return;
  }
  if (path === "/api/3d/submit" && method === "POST") {
    const b = await readBody(req);
    const c = effective3d(user.id, t3dCfgs());
    if (!c || !c.secretId || !c.secretKey) { res.statusCode = 400; res.end(JSON.stringify({ ok: false, error: "未配置混元 3D 密钥，请先在账号页填写 SecretId / SecretKey" })); return; }
    try {
      const resp = await submitHunyuan3D({ secretId: c.secretId, secretKey: c.secretKey, region: c.region, prompt: String(b.prompt || ""), resultFormat: "GLB" });
      res.end(JSON.stringify({ ok: true, jobId: resp.JobId || null, raw: resp }));
    } catch (e) {
      res.statusCode = 400;
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
    return;
  }
  if (path === "/api/3d/query" && method === "POST") {
    const b = await readBody(req);
    const c = effective3d(user.id, t3dCfgs());
    if (!c || !c.secretId || !c.secretKey) { res.statusCode = 400; res.end(JSON.stringify({ ok: false, error: "未配置混元 3D 密钥" })); return; }
    try {
      const resp = await queryHunyuan3D({ secretId: c.secretId, secretKey: c.secretKey, region: c.region, jobId: b.jobId });
      res.end(JSON.stringify({ ok: true, raw: resp }));
    } catch (e) {
      res.statusCode = 400;
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
    return;
  }
  // ---------- 图像生成配置（OpenAI 兼容，用户自配） ----------
  if (path === "/api/image/cfg" && method === "GET") {
    const c = effectiveImage(user.id, imgCfgs()) || {};
    res.end(JSON.stringify({ baseUrl: c.baseUrl || "", apiKey: c.apiKey ? "已配置" : "", model: c.model || "", source: c.source || "user" }));
    return;
  }
  if (path === "/api/image/cfg" && method === "PUT") {
    const b = await readBody(req);
    const all = imgCfgs();
    all[user.id] = { baseUrl: String(b.baseUrl || "").trim(), apiKey: String(b.apiKey || "").trim(), model: String(b.model || "gpt-image-2").trim(), updatedAt: now() };
    saveImgCfgs(all);
    res.end(JSON.stringify({ ok: true }));
    return;
  }
  if (path === "/api/ai-image" && method === "POST") {
    const b = await readBody(req);
    const c = effectiveImage(user.id, imgCfgs()) || {};
    if (!c.apiKey) { res.statusCode = 400; res.end(JSON.stringify({ ok: false, error: "未配置图像生成 API，请在模型设置中填写" })); return; }
    try {
      const base = (c.baseUrl || "https://api2.jojocode.com/v1").replace(/\/+$/, "");
      const model = c.model || "gpt-image-2";
      const r = await fetch(base + "/images/generations", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + c.apiKey },
        body: JSON.stringify({ model, prompt: String(b.prompt || "产品渲染图").slice(0, 2000), n: 1, size: "1024x1024" })
      });
      const j = await r.json();
      if (!r.ok) throw new Error((j.error && (j.error.message || j.error)) || "图像生成失败 HTTP " + r.status);
      const item = j.data && j.data[0];
      const url = item && (item.url || item.image_url || (item.b64_json ? "data:image/png;base64," + item.b64_json : "")) || j.url || "";
      if (!url) throw new Error("图像接口未返回图片地址");
      res.end(JSON.stringify({ ok: true, url }));
    } catch (e) {
      res.statusCode = 400;
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
    return;
  }
  // ---------- 项目导出（本地下载） ----------
  const expMatch = path.match(/^\/api\/projects\/([^/]+)\/export$/);
  if (expMatch && method === "GET") {
    const p = getProject(expMatch[1]);
    if (!p) { res.statusCode = 404; res.end(JSON.stringify({ error: "not found" })); return; }
    res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ ...p, data: p.data || {} }, null, 2));
    return;
  }
  if (path === "/api/profile/me" && method === "GET") {
    res.end(JSON.stringify({ username: user.username || "", bio: user.bio || "", profileColor: user.profileColor || null, email: user.email, onboardingCompletedAt: user.onboardingCompletedAt ?? null, roles: user.roles || [], useCases: user.useCases || [] }));
    return;
  }
  if (path === "/api/cad-wallet" && method === "GET") {
    res.end(JSON.stringify({ balance: 0, unlimited: false }));
    return;
  }
  if (path === "/api/set-username" && method === "POST") {
    const b = await readBody(req);
    const name = String(b.username || "").toLowerCase();
    if (!/^[a-z0-9_]{3,20}$/.test(name)) { res.statusCode = 400; res.end(JSON.stringify({ error: "用户名需为 3–20 个小写字母、数字或下划线" })); return; }
    if (users().some((u) => u.username && u.username.toLowerCase() === name && u.id !== user.id)) { res.statusCode = 409; res.end(JSON.stringify({ error: "That username is unavailable." })); return; }
    user.username = name; syncUser(user);
    res.end(JSON.stringify({ ok: true, username: user.username }));
    return;
  }
  if (path === "/api/set-bio" && method === "POST") { const b = await readBody(req); user.bio = String(b.bio || "").slice(0, 300); syncUser(user); res.end(JSON.stringify({ ok: true })); return; }
  if (path === "/api/set-profile-color" && method === "POST") { const b = await readBody(req); user.profileColor = b.color || null; syncUser(user); res.end(JSON.stringify({ ok: true })); return; }
  if (path === "/api/auto-username" && method === "POST") { if (!user.username) user.username = "用户" + user.id.slice(0, 6); syncUser(user); res.end(JSON.stringify({ username: user.username })); return; }
  if (path === "/api/onboarding/complete" && method === "POST") {
    const b = await readBody(req);
    if (user.onboardingCompletedAt) { res.end(JSON.stringify({ onboarding_completed_at: user.onboardingCompletedAt })); return; }
    user.onboardingCompletedAt = now();
    if (Array.isArray(b.roles)) user.roles = b.roles;
    if (Array.isArray(b.useCases)) user.useCases = b.useCases;
    syncUser(user);
    res.end(JSON.stringify({ onboarding_completed_at: user.onboardingCompletedAt }));
    return;
  }
  if (path === "/api/account" && method === "DELETE") {
    const { users: u, saveUsers } = await import("./store.mjs");
    const list = u().filter((x) => x.id !== user.id);
    saveUsers(list);
    res.end(JSON.stringify({ ok: true }));
    return;
  }
  if (path === "/api/star" && method === "POST") { const b = await readBody(req); const p = b.id ? getProject(b.id) : null; if (p) { p.starCount = (p.starCount || 0) + 1; saveProject(p); } res.end(JSON.stringify({ starred: true })); return; }
  if (path === "/api/publish" && method === "POST") { const b = await readBody(req); const p = b.id ? getProject(b.id) : null; if (p) { p.published = true; p.publishedAt = now(); saveProject(p); } res.end(JSON.stringify({ published: true })); return; }
  if (path === "/api/unpublish" && method === "POST") { const b = await readBody(req); const p = b.id ? getProject(b.id) : null; if (p) { p.published = false; saveProject(p); } res.end(JSON.stringify({ unpublished: true })); return; }
  if (path === "/api/export/zip" && method === "POST") {
    const b = await readBody(req);
    const p = b.id ? getProject(b.id) : null;
    if (!p) { res.statusCode = 404; res.end(JSON.stringify({ error: "not_found" })); return; }
    const d = p.data || {};
    const guideMd = ["# " + (d.projectName || ""), "", d.projectDescription || "", "", "## 组装指南", "", d.instructionPreamble || ""]
      .concat((d.instructionSteps || []).map((s) => `\n### ${s.title}\n` + (s.subSteps || []).map((ss) => `- ${ss.title}：${ss.detail || ""}`).join("\n"))).join("\n");
    const zip = makeZip([[`${p.projectName}.json`, JSON.stringify(d, null, 2)], [`build-guide.md`, guideMd]]);
    res.writeHead(200, { "Content-Type": "application/zip", "Content-Disposition": `attachment; filename="${encodeURIComponent(p.projectName)}.zip"` });
    res.end(zip);
    return;
  }
  if (path === "/api/parts/image" && method === "GET") {
    const name = url.searchParams.get("name") || "Part";
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120"><rect width="120" height="120" rx="8" fill="#111827"/><rect x="4" y="4" width="112" height="112" rx="6" fill="none" stroke="#22d3ee" stroke-width="1"/><text x="60" y="62" font-size="11" fill="#22d3ee" text-anchor="middle" font-family="monospace">${escXml(name.slice(0, 14))}</text></svg>`;
    res.writeHead(200, { "Content-Type": "image/svg+xml", "Cache-Control": "public, max-age=3600" });
    res.end(svg);
    return;
  }
  if (path.startsWith("/api/parts/") || path.startsWith("/api/broadcast") || path.startsWith("/api/project-invitations/accept") || path.startsWith("/api/share-links/redeem") || path.startsWith("/api/contact-leads") || path.startsWith("/api/collab/readme") || path.startsWith("/api/input-images")) {
    res.end(JSON.stringify({ ok: true, parts: [], data: null }));
    return;
  }
  if (path === "/api/cad-jobs/active" && method === "GET") { res.statusCode = 404; res.end("not found"); return; }

  res.statusCode = 404;
  res.end(JSON.stringify({ error: "not_found", path }));
}

function commItem(p) {
  return {
    id: p.id, token: p.id.slice(0, 12),
    projectName: p.data?.projectName || p.projectName,
    projectDescription: p.data?.projectDescription || "",
    nodeCount: p.data?.nodes?.length || 0, starCount: p.starCount || 0,
    publishedAt: p.updatedAt,
    ownerUsername: (users().find((u) => u.id === p.userId) || {}).username || "本地用户",
    ownerProfileColor: "#22c55e", thumbnailUrl: null,
  };
}
function normalizeProjectData(d) {
  const fixPart = (n) => {
    if (!n || typeof n !== "object") return n;
    const cost = Number(n.estimatedCost ?? n.price ?? n.estimated_price ?? 0);
    return {
      ...n,
      id: n.id || n.name || n.partId || ("p" + Math.random().toString(36).slice(2, 8)),
      estimatedCost: Number.isFinite(cost) ? cost : 0,
      quantity: n.quantity ?? n.qty ?? 1,
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
function projectPublic(p) {
  const d = p.data || {};
  const nodeCount = Array.isArray(d.nodes) ? d.nodes.length : (p.nodeCount || 0);
  return {
    id: p.id, projectName: d.projectName || p.projectName || "未命名项目",
    projectDescription: d.projectDescription || p.projectDescription || "",
    nodeCount, partsCount: Array.isArray(d.parts) ? d.parts.length : 0, starCount: p.starCount || 0,
    createdAt: p.createdAt, updatedAt: p.updatedAt, version: p.version, historyEpoch: p.historyEpoch,
    published: !!p.published, thumbnailUrl: null,
  };
}

async function handleProject(req, res, url, projMatch, method, user) {
  const pid = projMatch[1];
  const rest = projMatch[2] || "";
  const p = getProject(pid);
  if (!p || p.userId !== user.id) { res.statusCode = 404; res.end(JSON.stringify({ error: "not_found" })); return; }
  if (rest === "/head" && method === "GET") {
    res.end(JSON.stringify({ version: p.version || 1, historyEpoch: p.chat?.historyEpoch || 1 }));
    return;
  }
  if (rest === "/versions" && method === "GET") {
    res.end(JSON.stringify({ activeChatHeadSeq: p.chat?.activeChatHeadSeq ?? null, currentVersion: p.version || 1, historyEpoch: p.chat?.historyEpoch || 1, checkpoints: [] }));
    return;
  }
  if (rest === "" && method === "GET") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ...projectPublic(p), ...(normalizeProjectData(p.data) || {}), turns: p.turns || [], chat: p.chat || emptyChat(), userId: p.userId }));
    return;
  }
  if (rest === "" && method === "DELETE") {
    saveProjects(projects().filter((x) => x.id !== pid));
    res.end(JSON.stringify({ ok: true }));
    return;
  }
  if (rest === "/chat" && method === "GET") {
    res.writeHead(200, { "Content-Type": "application/json" });
    const c = p.chat || emptyChat();
    res.end(JSON.stringify({ ...c, turns: p.turns || c.turns || [], enabled: c.enabled ?? true, version: p.version || c.version || 1, historyEpoch: c.historyEpoch ?? 1, revision: c.revision ?? 0, activity: c.activity ?? false, images: Array.isArray(c.images) ? c.images : [] }));
    return;
  }
  if (rest === "/chat" && method === "POST") {
    const b = await readBody(req);
    if (b.value && Array.isArray(b.value.turns)) {
      p.turns = b.value.turns;
      p.chat = { ...(p.chat || emptyChat()), ...b.value, turns: p.turns };
      p.version = p.chat.version || p.version;
    } else if (b.turns && Array.isArray(b.turns)) {
      p.turns = b.turns;
      p.chat = { ...(p.chat || emptyChat()), turns: p.turns };
    }
    if (b.responseMode === "ack" && b.idempotencyKey) {
      p.updatedAt = now();
      saveProject(p);
      res.end(JSON.stringify({ accepted: true, id: p.id, version: p.version || 1, historyEpoch: p.chat?.historyEpoch || 1 }));
      return;
    }
    p.updatedAt = now();
    saveProject(p);
    const c = p.chat || emptyChat();
    res.end(JSON.stringify({ ...c, turns: p.turns || c.turns || [], enabled: c.enabled ?? true, version: p.version || c.version || 1, historyEpoch: c.historyEpoch ?? 1, revision: c.revision ?? 0, activity: c.activity ?? false, images: Array.isArray(c.images) ? c.images : [] }));
    return;
  }
  if (rest === "/chat/clear" && method === "POST") {
    p.chat = { ...emptyChat(), historyEpoch: (p.chat?.historyEpoch || 1) + 1 };
    p.turns = [];
    p.chat.turns = [];
    p.updatedAt = now();
    saveProject(p);
    res.end(JSON.stringify({ cleared: true }));
    return;
  }
  if (rest.startsWith("/image-rerolls/")) {
    res.statusCode = 501; res.end(JSON.stringify({ error: "unsupported" })); return;
  }
  res.statusCode = 404;
  res.end(JSON.stringify({ error: "not_found" }));
}

// ---------------- SSE 生成 ----------------
function sseEvent(res, event, data) {
  const payload = typeof data === "string" ? data : JSON.stringify(data);
  res.write(`event: ${event}\ndata: ${payload}\n\n`);
}
async function runGemini(req, res, user) {
  const body = await readBody(req);
  const action = body.action;
  const payload = body.payload || {};
  const projectId = payload.projectId;
  const cfg = effectiveLlm(user.id, userCfgs());
  const prompt = payload.prompt || payload.idea || payload.message || payload.userMessage || "";
  console.log("[gemini]", action, "projectId=" + projectId, "prompt=" + String(prompt).slice(0, 80));

  if (action === "resetSession") { res.writeHead(200, { "Content-Type": "application/json" }); res.end("{}"); return; }

  res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive", "X-Accel-Buffering": "no" });
  const pingTimer = setInterval(() => { try { sseEvent(res, "ping", {}); } catch {} }, 12000);
  req.on("close", () => clearInterval(pingTimer));
  const emit = (ev, data) => { try { sseEvent(res, ev, data); } catch { clearInterval(pingTimer); } };

  try {
    emit("ping", {});
    emit("queued", { position: 0 });
    emit("running", {});

    let result;
    const docOf = (d) => (d && d.projectName) || (d && d.nodes);
    switch (action) {
      case "generatePlan":
      case "planFollowUp":
      case "executeFollowUp":
      case "askFollowUp": {
        await sleep(300);
        const doc = await generateDoc(prompt, cfg);
        const turn = { id: uuid(), actorId: "assistant", role: "assistant", prompt: null, value: doc, revision: 0, createdAt: now(), status: "complete" };
        result = doc;
        if (projectId && !String(projectId).startsWith("draft")) {
          const p = getProject(projectId);
          if (p) {
            p.data = { ...(p.data || {}), ...doc, projectName: doc.projectName, projectDescription: doc.projectDescription };
            p.projectName = doc.projectName;
            p.updatedAt = now();
            p.nodeCount = (doc.nodes || []).length;
            addTurn(p, turn);
          }
        }
        const t = now();
        result = {
          id: projectId || uuid(), key: projectId || uuid(), projectId: projectId || null,
          status: "complete", phase: "complete", step: "done", revision: 1,
          modelProvider: cfg?.provider || "local", modelTier: "local",
          projectName: doc.projectName || null, prompt,
          subStatus: {}, failure: null, questionRounds: [], questionsLoading: false,
          projectData: doc,
          sections: { parts: true, wiring: true, mech: true, info: true, guide: true },
          flags: { guide: true, image: false, info: false },
          messages: [
            { role: "user", content: prompt, timestamp: t },
            { id: turn.id, actorId: "assistant", role: "assistant", content: null, timestamp: t, revision: 0, value: doc, status: "complete" }
          ],
          inputImages: [], isComplete: true, savedVersion: 1, historyEpoch: 0,
          startedAt: t, updatedAt: t
        };
        break;
      }
      case "generateElectrical":
        await sleep(300);
        result = { nodes: demoDoc(prompt).nodes, wiring: demoDoc(prompt).wiring, electricalConnections: demoDoc(prompt).electricalConnections };
        break;
      case "generateElectricalNodes":
        await sleep(200); result = { nodes: demoDoc(prompt).nodes }; break;
      case "generateElectricalConnections":
      case "enhanceElectricalConnections":
        await sleep(200); result = { wiring: demoDoc(prompt).wiring, electricalConnections: demoDoc(prompt).electricalConnections }; break;
      case "generateMechanicalNodes":
        await sleep(200); result = { mechanical: demoDoc(prompt).mechanical }; break;
      case "generateMechanicalConnections":
      case "enrichMechanicalConnections":
      case "healMechanicalConnections":
        await sleep(200); result = { mechanicalConnections: demoDoc(prompt).mechanicalConnections }; break;
      case "generateGuide": {
        await sleep(200); const d = demoDoc(prompt);
        result = { instructionPreamble: d.instructionPreamble, instructionSteps: d.instructionSteps };
        break;
      }
      case "generateSubStepDetail":
        result = { detail: "参考方案中的说明完成此步骤，注意核对接线与打印参数。" }; break;
      case "generateStepImage":
      case "generateProjectImage":
        result = { imageUrl: null }; break;
      case "searchParts": {
        const d = demoDoc(prompt);
        result = { parts: (d.parts || []).map((pp, i) => ({ ...pp, imageUrl: `/api/parts/image?name=${encodeURIComponent(pp.name)}&i=${i}` })) };
        break;
      }
      case "researchPartSection":
        result = { sections: [] }; break;
      case "generateIdeas":
        result = ["智能台灯", "桌面气象站", "六自由度机械臂", "Wi-Fi 遥控小车"]; break;
      case "generateSuggestedPrompts":
        result = ["做一个能自动避障的小车", "设计一个桌面气象站", "做一个智能触控台灯", "六自由度机械臂抓取演示"]; break;
      case "generateSuggestedImagePrompts":
        result = ["top-down blueprint style drawing of the project", "isometric 3d render of the assembled device"]; break;
      case "generateQuestions":
        result = [{ question: "你想做一个什么样的项目？", options: [] }]; break;
      case "generateInfo":
        result = {}; break;
      default:
        result = {};
    }
    emit("done", { data: result });
    clearInterval(pingTimer);
    try { res.end(); } catch {}
  } catch (e) {
    emit("error", { message: e.message || "Generation failed", kind: "generation_failed" });
    clearInterval(pingTimer);
    try { res.end(); } catch {}
  }
}
function addTurn(p, turn) {
  p.turns = p.turns || [];
  const i = p.turns.findIndex((t) => t.id === turn.id);
  if (i >= 0) p.turns[i] = turn; else p.turns.push(turn);
  p.chat = p.chat || emptyChat();
  p.chat.turns = p.turns;
  p.chat.revision = (p.chat.revision || 0) + 1;
  p.chat.version = (p.version || 1) + 1;
  p.chat.historyEpoch = p.chat.historyEpoch || 1;
  p.version = p.chat.version;
  saveProject(p);
}

// ---------------- generation-runs（原版 admit → poll → completed 生命周期） ----------------
const runsByUser = new Map(); // user.id -> Map(id -> run)

function newRun(id, prompt, opts) {
  const t = now();
  return {
    id, key: id, status: "queued", projectId: opts.targetProjectId || null,
    projectName: null, prompt: String(prompt || ""), phase: "planning", step: "admitting",
    revision: 0, subStatus: {}, failure: null, questionRounds: [], questionsLoading: false,
    projectData: null,
    sections: { parts: false, wiring: false, mech: false, info: false, guide: false },
    messages: [{ role: "user", content: String(prompt || ""), timestamp: t }],
    flags: { guide: false, image: false, info: false },
    inputImages: Array.isArray(opts.inputImages) ? opts.inputImages.map((x) => ({ id: x })) : [],
    isComplete: false, savedVersion: null, historyEpoch: opts.historyEpoch ?? 0,
    modelProvider: opts.modelProvider || "local", modelTier: opts.modelTier || "local",
    startedAt: t, updatedAt: t
  };
}

function completeRun(run, doc) {
  const t = now();
  const userMsg = run.messages[0] || { role: "user", content: run.prompt || "", timestamp: run.startedAt };
  const turn = { id: uuid(), actorId: "assistant", role: "assistant", prompt: null, value: doc, revision: 0, createdAt: t, status: "complete" };
  run.status = "completed"; run.phase = "complete"; run.step = "done";
  run.revision = 1; run.subStatus = {}; run.failure = null;
  run.projectData = doc; run.projectName = doc.projectName || run.projectName;
  run.sections = { parts: true, wiring: true, mech: true, info: true, guide: true };
  run.flags = { guide: true, image: false, info: false };
  run.messages = [userMsg, { id: turn.id, actorId: "assistant", role: "assistant", content: null, timestamp: t, revision: 0, value: doc, status: "complete" }];
  run.isComplete = true; run.savedVersion = 1; run.updatedAt = t;
  return turn;
}

async function handleGenerationRuns(req, res, url, method, user) {
  const path = url.pathname;
  const rest = path.slice("/api/generation-runs".length);
  let mine = runsByUser.get(user.id);
  if (!mine) { mine = new Map(); runsByUser.set(user.id, mine); }

  if (method === "POST" && (rest === "" || rest === "/")) {
    const b = await readBody(req);
    const id = uuid();
    const run = newRun(id, b.prompt, {
      targetProjectId: b.targetProjectId || null, historyEpoch: b.historyEpoch,
      inputImages: b.inputImages || [], modelProvider: b.modelProvider, modelTier: b.modelTier
    });
    mine.set(id, run);
    run.status = "running"; run.step = "planning"; run.updatedAt = now();
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(run));
    (async () => {
      try {
        const cfg = effectiveLlm(user.id, userCfgs());
        const doc = await generateDoc(run.prompt || "", cfg);
        let p = run.projectId ? getProject(run.projectId) : null;
        if (!p) { p = newProject(user.id, doc); }
        else {
          p.data = { ...(p.data || {}), ...doc, projectName: doc.projectName, projectDescription: doc.projectDescription };
          p.projectName = doc.projectName; p.updatedAt = now();
          p.nodeCount = (doc.nodes || []).length;
        }
        saveProject(p);
        const turn = completeRun(run, doc);
        if (!String(p.id).startsWith("draft")) {
          addTurn(p, turn);
          run.projectId = p.id;
        }
      } catch (e) {
        run.status = "failed"; run.phase = "idle";
        run.failure = { phase: "planning", kind: "route", message: e.message || "Generation failed" };
        run.updatedAt = now();
      }
    })();
    return;
  }

  if (method === "GET" && (rest === "" || rest === "/")) {
    res.end(JSON.stringify([...mine.values()]));
    return;
  }

  const idMatch = rest.match(/^\/([^/?]+)(\/.*)?$/);
  if (idMatch) {
    const id = decodeURIComponent(idMatch[1]);
    const sub = idMatch[2] || "";
    const run = mine.get(id);
    if (method === "GET" && sub === "") {
      res.writeHead(run ? 200 : 404, { "Content-Type": "application/json" });
      res.end(JSON.stringify(run || { error: "run_not_found" }));
      return;
    }
    if (method === "POST" && sub === "/cancel") {
      if (run) {
        run.status = "cancelled"; run.phase = "idle"; run.failure = null; run.updatedAt = now();
      }
      res.end(JSON.stringify(run || { error: "run_not_found" }));
      return;
    }
    if (method === "POST" && sub === "/retry") {
      if (run) {
        run.status = "queued"; run.phase = "planning"; run.step = "admitting";
        run.failure = null; run.isComplete = false; run.updatedAt = now();
        res.end(JSON.stringify(run));
        (async () => {
          try {
            const cfg = effectiveLlm(user.id, userCfgs());
            const doc = await generateDoc(run.prompt || "", cfg);
            let p = run.projectId ? getProject(run.projectId) : null;
            if (!p) { p = newProject(user.id, doc); }
            saveProject(p);
            const turn = completeRun(run, doc);
            if (!String(p.id).startsWith("draft")) { addTurn(p, turn); run.projectId = p.id; }
          } catch (e) {
            run.status = "failed"; run.phase = "idle";
            run.failure = { phase: "planning", kind: "route", message: e.message || "Generation failed" };
            run.updatedAt = now();
          }
        })();
      } else {
        res.statusCode = 404; res.end(JSON.stringify({ error: "run_not_found" }));
      }
      return;
    }
    if (method === "POST" && sub === "/questions") {
      const b = await readBody(req);
      if (run) {
        run.questionRounds = Array.isArray(b.qa) ? b.qa : [];
        run.questionsLoading = false; run.revision = (run.revision || 0) + 1; run.updatedAt = now();
      }
      res.end(JSON.stringify(run || { error: "run_not_found" }));
      return;
    }
    res.statusCode = 404; res.end(JSON.stringify({ error: "not_found" }));
    return;
  }

  res.statusCode = 404; res.end(JSON.stringify({ error: "not_found" }));
}
function syncUser(u) {
  const list = users();
  const i = list.findIndex((x) => x.id === u.id);
  if (i >= 0) list[i] = u;
  saveUsers(list);
}

// ---------------- 简易 ZIP（store 方式） ----------------
function crc32(buf) {
  let c = ~0;
  for (const b of buf) { c ^= b; for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1; }
  return ~c >>> 0;
}
function makeZip(files) {
  const enc = new TextEncoder();
  const out = [];
  const central = [];
  let offset = 0;
  for (const [name, content] of files) {
    const data = typeof content === "string" ? enc.encode(content) : Buffer.from(content);
    const nameBuf = Buffer.from(name, "utf8");
    const crc = crc32(data);
    const lh = Buffer.alloc(30);
    lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(20, 4); lh.writeUInt16LE(0, 6); lh.writeUInt16LE(0, 8);
    lh.writeUInt16LE(0, 10); lh.writeUInt16LE(0, 12); lh.writeUInt32LE(crc, 14);
    lh.writeUInt32LE(data.length, 18); lh.writeUInt32LE(data.length, 22); lh.writeUInt16LE(nameBuf.length, 26); lh.writeUInt16LE(0, 28);
    out.push(Buffer.concat([lh, nameBuf, Buffer.from(data)]));
    const ch = Buffer.alloc(46);
    ch.writeUInt32LE(0x02014b50, 0); ch.writeUInt16LE(20, 4); ch.writeUInt16LE(20, 6); ch.writeUInt16LE(0, 8);
    ch.writeUInt16LE(0, 10); ch.writeUInt16LE(0, 12); ch.writeUInt16LE(0, 14); ch.writeUInt32LE(crc, 16);
    ch.writeUInt32LE(data.length, 20); ch.writeUInt32LE(data.length, 24); ch.writeUInt16LE(nameBuf.length, 28);
    ch.writeUInt16LE(0, 30); ch.writeUInt16LE(0, 32); ch.writeUInt16LE(0, 34); ch.writeUInt16LE(0, 36);
    ch.writeUInt32LE(0, 38); ch.writeUInt32LE(offset, 42);
    central.push(Buffer.concat([ch, nameBuf]));
    offset += out[out.length - 1].length;
  }
  const centralStart = offset;
  const centralBuf = Buffer.concat(central);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0); eocd.writeUInt16LE(0, 4); eocd.writeUInt16LE(0, 6);
  eocd.writeUInt16LE(files.length, 8); eocd.writeUInt16LE(files.length, 10);
  eocd.writeUInt32LE(centralBuf.length, 12); eocd.writeUInt32LE(centralStart, 16); eocd.writeUInt16LE(0, 20);
  return Buffer.concat([...out, centralBuf, eocd]);
}
function escXml(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
