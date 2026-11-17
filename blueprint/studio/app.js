// app.js - BLUEAI 智造工作台前端（3D 工坊 + 课程模式）
// 纯原生 JS，无构建步骤：所有能力都走 9418 同源网关（/yxz + /api/studio）。
(() => {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const PX = "/yxz"; // 宜小智能力服务前缀

  const state = {
    view: "make",
    level: "middle",
    projectId: null,
    projects: [],
    course: null,
    sessionId: null,
    previews: [],
    selected: -1,
    model: null,
    tripoOpen: false,
    progressTimer: null,
  };

  // ---------------- 基础工具 ----------------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  let toastTimer = null;
  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
  }
  function token() {
    try {
      const local = localStorage.getItem("blueai-studio-auth");
      if (local) {
        const v = JSON.parse(local);
        if (v && v.access_token) return v.access_token;
        if (v && v.session && v.session.access_token) return v.session.access_token;
      }
      for (const k of Object.keys(localStorage)) {
        if (!k.includes("auth-token")) continue;
        const v = JSON.parse(localStorage.getItem(k));
        if (v && v.access_token) return v.access_token;
        if (v && v.session && v.session.access_token) return v.session.access_token;
      }
    } catch {}
    return null;
  }
  async function ensureLocalSession() {
    if (token()) return;
    try {
      const r = await fetch("/auth/v1/local", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-BlueAI-Studio": "1" },
        body: "{}",
      });
      if (!r.ok) return;
      const s = await r.json();
      if (s && s.access_token) localStorage.setItem("blueai-studio-auth", JSON.stringify(s));
    } catch {}
  }
  async function api(path, opts = {}) {
    const headers = { "Content-Type": "application/json" };
    const t = token();
    if (t) headers.Authorization = "Bearer " + t;
    const r = await fetch(path, { method: opts.method || "GET", headers: { ...headers, ...(opts.headers || {}) }, body: opts.body ? JSON.stringify(opts.body) : undefined });
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
    if (!r.ok) {
      let msg = (data && (data.msg || data.error || data.detail)) || ("HTTP " + r.status);
      if (data && data.detail && typeof data.detail === "object") {
        msg = data.detail.hint || data.detail.error || data.detail.message || data.detail.detail || JSON.stringify(data.detail);
      }
      const err = new Error(msg);
      err.status = r.status;
      err.data = data;
      throw err;
    }
    return data;
  }
  async function yxz(path, opts = {}) {
    return api(PX + path, opts);
  }
  const fixUrl = (u) => (u && u.startsWith("/api/") ? PX + u : u);

  // ---------------- 视图切换 ----------------
  $$(".tab").forEach((btn) => btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    const v = btn.dataset.view;
    state.view = v;
    $$(".view").forEach((s) => s.classList.toggle("active", s.id === "view-" + v));
    if (v === "projects") renderProjects();
    if (v === "course") renderCourseProjects();
  }));

  // ---------------- 服务状态 ----------------
  async function refreshStatus() {
    try {
      const s = await api("/api/studio/status");
      const alive = s.yxz && s.yxz.alive;
      $("#svc-dot").className = "dot " + (alive ? "ok" : "bad");
      const h = (s.yxz && s.yxz.health) || {};
      const tripo = h.tripo3d_key_loaded
        ? (h.tripo3d_ok
          ? (Number(h.tripo3d_balance || 0) > 0 ? "立体生成可用" : "立体额度用尽")
          : "立体生成待恢复")
        : "立体生成未配置";
      $("#svc-text").textContent = alive ? `3D 服务就绪 · ${tripo}` : "3D 服务未启动";
      const canMake = alive && h.tripo3d_ok === true && Number(h.tripo3d_balance || 0) > 0;
      const btn3d = $("#btn-3d");
      if (btn3d && !btn3d.dataset.busy) {
        btn3d.disabled = !canMake;
        btn3d.textContent = canMake ? "生成 3D 模型" : "立体额度用尽";
      }
      const hint = $("#engine-hint");
      state.tripoOpen = false;
      if (hint) {
        if (h.tripo3d_ok === true) {
          hint.className = "engine-hint ok";
          hint.textContent = "立体模型：Tripo 可用 · 生成后可下载 STL / GLB";
        } else if (h.tripo3d_checking) {
          hint.className = "engine-hint";
          hint.textContent = "正在检查立体模型引擎…";
        } else {
          state.tripoOpen = true;
          hint.className = "engine-hint warn";
          hint.textContent = "立体模型暂不可用（Tripo 密钥 403 / 额度异常）；可先生成 2.5D 浮雕，尺寸与切片仍可用。";
        }
      }
      if (alive) loadSoftware();
    } catch {
      $("#svc-dot").className = "dot bad";
      $("#svc-text").textContent = "网关未响应";
    }
  }

  // ---------------- 3D：预览 ----------------
  function setPipeline(n) {
    $$(".pipeline li").forEach((li) => {
      const i = Number(li.dataset.step);
      li.classList.toggle("active", i === n);
      li.classList.toggle("done", i < n);
    });
  }

  $("#chips")?.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-p]");
    if (!b) return;
    $("#prompt").value = b.dataset.p;
    $("#prompt").focus();
  });

  $("#btn-preview")?.addEventListener("click", async () => {
    const prompt = $("#prompt").value.trim();
    if (!prompt) { $("#prompt").focus(); return toast("先写一句你想做的东西"); }
    const btn = $("#btn-preview");
    btn.disabled = true;
    $("#preview-hint").textContent = "正在生成 4 张设计稿…（云端生图约 20–60 秒）";
    try {
      const r = await yxz("/api/previews", { method: "POST", body: { prompt, n: 4, session_id: state.sessionId || "" } });
      state.sessionId = r.session_id;
      state.previews = (r.previews || []).map((p) => ({ ...p, url: fixUrl(p.path) }));
      state.selected = state.previews.length ? 0 : -1;
      renderPreviews();
      $("#session-label").textContent = "会话 " + state.sessionId;
      $("#btn-3d").disabled = state.selected < 0;
      setPipeline(2);
      $("#preview-hint").textContent = "已生成 · 通道 " + (r.source || "auto");
      if (!state.previews.length) toast("这次没有出图，换个描述再试一次");
    } catch (e) {
      $("#preview-hint").textContent = "生成失败：" + e.message;
      toast("生成失败：" + e.message);
    } finally {
      btn.disabled = false;
    }
  });

  function renderPreviews() {
    const grid = $("#preview-grid");
    if (!state.previews.length) {
      grid.innerHTML = `<div class="empty"><div class="empty-mark">◇</div><p>生成预览后，这里会出现 4 张设计稿</p></div>`;
      return;
    }
    grid.innerHTML = state.previews.map((p, i) => `
      <div class="preview-item ${i === state.selected ? "on" : ""}" data-i="${i}">
        <img src="${p.url}" alt="设计稿 ${i + 1}" loading="lazy" />
        <span class="tag">${esc(p.tag || p.source || "预览")}</span>
        <span class="pick">已选</span>
      </div>`).join("");
    $$(".preview-item", grid).forEach((el) => el.addEventListener("click", () => {
      state.selected = Number(el.dataset.i);
      $$(".preview-item", grid).forEach((x) => x.classList.toggle("on", x === el));
      $("#btn-3d").disabled = false;
    }));
  }

  // ---------------- 3D：生成模型 ----------------
  $("#btn-3d")?.addEventListener("click", async () => {
    if (!state.sessionId || state.selected < 0) return;
    if (state.tripoOpen) {
      $("#m-progress").textContent = "立体模型暂不可用（Tripo 密钥 403 / 额度异常）；请点「生成 2.5D 浮雕」";
      $("#btn-fallback").style.display = "";
      toast("立体模型暂不可用，可先生成 2.5D 浮雕");
      return;
    }
    const btn = $("#btn-3d");
    btn.disabled = true;
    setPipeline(3);
    $("#model-title").textContent = "正在生成…";
    $("#m-progress").textContent = "正在上传设计稿";
    $("#m-bar").style.width = "5%";
    startProgress();
    try {
      const r = await yxz("/api/3d_tripo", { method: "POST", body: { session_id: state.sessionId, image_index: state.selected } });
      state.model = r;
      $("#model-title").textContent = "模型已生成";
      $("#m-engine").textContent = r.engine || "tripo3d";
      $("#m-faces").textContent = (r.faces || 0).toLocaleString();
      $("#m-size").textContent = Array.isArray(r.extents_mm) ? r.extents_mm.map((x) => Number(x).toFixed(0)).join(" × ") + " mm" : "—";
      $("#m-time").textContent = (r.elapsed_s || 0) + " s";
      $("#m-bar").style.width = "100%";
      $("#m-progress").textContent = "完成 · 可下载 STL / GLB";
      const glb = fixUrl(r.model_url);
      const stl = fixUrl(r.stl_url || (r.model_url || "").replace("mesh.glb", "mesh.stl"));
      $("#btn-glb").style.display = ""; $("#btn-glb").href = glb; $("#btn-glb").setAttribute("download", "model.glb");
      $("#btn-stl").style.display = ""; $("#btn-stl").href = stl; $("#btn-stl").setAttribute("download", "model.stl");
      showModel(glb);
      setPipeline(4);
      loadSoftware();
      toast("3D 模型已生成，可下载或直接打开切片软件");
    } catch (e) {
      $("#model-title").textContent = "生成失败";
      $("#m-progress").textContent = "失败：" + e.message + "（可点「本地浮雕兜底」）";
      $("#m-bar").style.width = "0%";
      $("#btn-fallback").style.display = "";
      toast("3D 生成失败：" + e.message);
      setPipeline(2);
    } finally {
      btn.disabled = false;
      stopProgress();
    }
  });

  // 云端 Tripo 不可用时的本地兜底：按设计稿叠层生成可打印浮雕（不需要 GPU）
  $("#btn-fallback")?.addEventListener("click", async () => {
    if (!state.sessionId || state.selected < 0) return;
    const btn = $("#btn-fallback");
    btn.disabled = true;
    $("#btn-3d").disabled = true;
    $("#model-title").textContent = "正在生成浮雕…";
    $("#m-progress").textContent = "正在按设计稿叠层";
    $("#m-bar").style.width = "20%";
    try {
      const r = await yxz("/api/3d_cartoon", { method: "POST", body: { session_id: state.sessionId, image_index: state.selected } });
      state.model = r;
      const glb = fixUrl(r.model_url);
      const stl = PX + `/api/data/${state.sessionId}/model_relief/mesh.stl`;
      $("#model-title").textContent = "浮雕模型已生成";
      $("#m-engine").textContent = "local-relief";
      $("#m-faces").textContent = (r.faces || 0).toLocaleString();
      $("#m-size").textContent = Array.isArray(r.extents_mm) ? r.extents_mm.map((x) => Number(x).toFixed(0)).join(" × ") + " mm" : "—";
      $("#m-time").textContent = r.elapsed_s ? r.elapsed_s + " s" : "—";
      $("#m-bar").style.width = "100%";
      $("#m-progress").textContent = "完成 · 可下载 STL";
      $("#btn-glb").style.display = ""; $("#btn-glb").href = glb; $("#btn-glb").setAttribute("download", "relief.glb");
      $("#btn-stl").style.display = ""; $("#btn-stl").href = stl; $("#btn-stl").setAttribute("download", "relief.stl");
      showModel(glb);
      setPipeline(4);
      $("#btn-fallback").style.display = "none";
      toast("浮雕模型已生成，可直接切片打印");
    } catch (e) {
      toast("浮雕兜底也失败了：" + e.message);
    } finally {
      btn.disabled = false;
      $("#btn-3d").disabled = !state.sessionId || state.selected < 0;
    }
  });

  function startProgress() {
    stopProgress();
    let since = 0;
    state.progressTimer = setInterval(async () => {
      if (!state.sessionId) return;
      try {
        const r = await yxz(`/api/progress/${state.sessionId}?since=${since}`);
        const evs = r.events || [];
        if (evs.length) {
          since = evs[evs.length - 1].ts || since;
          const last = evs[evs.length - 1];
          const msg = last.message || last.label || last.step || "";
          if (msg) $("#m-progress").textContent = msg;
          if (last.pct != null) $("#m-bar").style.width = Math.max(5, Number(last.pct)) + "%";
        }
      } catch {}
    }, 1200);
  }
  function stopProgress() {
    if (state.progressTimer) clearInterval(state.progressTimer);
    state.progressTimer = null;
  }

  function scrollToModel() {
    const card = $("#model-card");
    if (!card) return;
    const top = card.getBoundingClientRect().top + window.scrollY - 24;
    window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
  }
  function showModel(url) {
    const host = $("#model-view");
    // Always mount the element: model-viewer is loaded as an async module,
    // so the custom element may not be registered yet at handoff time.
    // The browser upgrades it as soon as the module lands.
    host.innerHTML = "";
    const mv = document.createElement("model-viewer");
    mv.setAttribute("src", url);
    mv.setAttribute("alt", "3D 模型");
    mv.setAttribute("camera-controls", "");
    mv.setAttribute("auto-rotate", "");
    mv.setAttribute("touch-action", "pan-y");
    mv.setAttribute("shadow-intensity", "0.6");
    mv.setAttribute("exposure", "1.0");
    host.appendChild(mv);
  }

  // ---------------- 预制模型 ----------------
  async function loadPresets() {
    try {
      const r = await yxz("/api/presets/models");
      const items = r.items || [];
      $("#preset-mini").innerHTML = items.map((it) => `
        <div class="preset-mini-item" data-glb="${esc(fixUrl(it.glbUrl))}" data-stl="${esc(fixUrl(it.stlUrl || ""))}" data-name="${esc(it.name)}">
          <img src="${esc(fixUrl(it.thumbUrl || ""))}" alt="${esc(it.name)}" />
          <div><strong>${esc(it.name)}</strong><span>${esc(it.id)}</span></div>
        </div>`).join("");
      $$(".preset-mini-item").forEach((el) => el.addEventListener("click", () => {
        const glb = el.dataset.glb, stl = el.dataset.stl;
        $("#model-title").textContent = el.dataset.name + " · 预制模型";
        $("#m-engine").textContent = "preset";
        $("#m-faces").textContent = "—";
        $("#m-size").textContent = "—";
        $("#m-time").textContent = "—";
        $("#m-progress").textContent = "预制摆件，可直接下载打印";
        $("#m-bar").style.width = "100%";
        $("#btn-glb").style.display = ""; $("#btn-glb").href = glb; $("#btn-glb").setAttribute("download", el.dataset.name + ".glb");
        if (stl) { $("#btn-stl").style.display = ""; $("#btn-stl").href = stl; $("#btn-stl").setAttribute("download", el.dataset.name + ".stl"); }
        showModel(glb);
        setPipeline(1);
      }));
    } catch {}
  }

  // ---------------- 名片 ----------------
  $("#btn-card")?.addEventListener("click", async () => {
    const btn = $("#btn-card");
    btn.disabled = true;
    try {
      const body = {
        name: $("#card-name").value.trim(),
        title: $("#card-title").value.trim(),
        contact: $("#card-contact").value.trim(),
        slogan: $("#card-slogan").value.trim(),
        back_template: "activity_yichang",
        artwork_session_id: state.sessionId || null,
        artwork_image_index: state.selected >= 0 ? state.selected : 0,
      };
      const r = await yxz("/api/laser_card", { method: "POST", body });
      $("#btn-card-png").style.display = ""; $("#btn-card-png").href = fixUrl(r.png_url);
      $("#btn-card-svg").style.display = ""; $("#btn-card-svg").href = fixUrl(r.svg_url);
      const size = Array.isArray(r.size_mm) ? r.size_mm.join(" × ") : r.size_mm;
      toast(`名片已生成（${size} mm），可打开 SVG 交给激光软件`);
    } catch (e) {
      toast("名片生成失败：" + e.message);
    } finally { btn.disabled = false; }
  });

  // ---------------- 本机软件 ----------------
  let softwareCache = [];
  async function loadSoftware() {
    try {
      const r = await yxz("/api/software/detect");
      softwareCache = r.tools || [];
      const host = $("#software-list");
      if (!softwareCache.length) { host.innerHTML = "<em>未检测到本机工具</em>"; return; }
      host.innerHTML = softwareCache.map((t) => {
        const ok = t.available || t.installed || t.path;
        return `<button class="sw ${ok ? "ok" : "no"}" data-id="${esc(t.id)}" ${ok ? "" : "disabled"} title="${esc(t.path || "")}">${esc(t.name || t.id)}</button>`;
      }).join("");
      $$(".sw.ok", host).forEach((el) => el.addEventListener("click", async () => {
        if (!state.sessionId || !state.model) return toast("先生成一个 3D 模型，再用本机软件打开");
        try {
          await yxz("/api/software/open", { method: "POST", body: { software_id: el.dataset.id, session_id: state.sessionId, fmt: "stl", image_index: state.selected } });
          toast("已尝试用 " + el.textContent + " 打开模型");
        } catch (e) { toast("打开失败：" + e.message); }
      }));
    } catch {
      $("#software-list").innerHTML = "<em>3D 服务未启动</em>";
    }
  }

  // ---------------- 3D 助手对话 ----------------
  function makeChat(text, who = "bot") {
    const log = $("#make-chat");
    const d = document.createElement("div");
    d.className = "msg " + who;
    d.textContent = text;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
  }
  $("#make-send")?.addEventListener("click", () => sendMake());
  $("#make-input")?.addEventListener("keydown", (e) => { if (e.key === "Enter") sendMake(); });
  async function sendMake() {
    const input = $("#make-input");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    makeChat(text, "user");
    const tips = [
      /倒|方向|反|躺/, "模型倒着通常是因为坐标轴不同：Tripo 出来是 Y 轴朝上，打印要用 Z 轴朝上。点生成时后端会做一次「立正 + 平底」处理，下载 STL 后用切片软件看一眼摆放就行。",
      /stl|切片|打印|bambu|orca|cura/, "STL 下载后直接拖进 Bambu Studio / OrcaSlicer：先确认尺寸（高约 70mm），再选 0.2mm 层高、10% 填充，加不加支撑看悬空角度。",
      /激光|名片|svg/, "名片导出是毫米单位 SVG：红线切割、绿线雕刻、十字定位。先在 xTool Studio 或 LightBurn 里预览，再上机。",
      /模型|3d|生成/, "先写一句具体描述（材质 + 姿势 + 风格），生成 4 张预览挑一张最像的，再点「生成 3D 模型」。描述越具体，模型越准。",
    ];
    const hit = tips.find(([re]) => re.test(text));
    makeChat(hit ? hit[1] : "我在。你可以换个更具体的描述再生成一版（比如加上「圆润」「白色」「双手叉腰」），或者直接点右侧预制摆件看一个已经做好的宜小智模型。");
  }

  // ---------------- 课程 ----------------
  async function loadProjects() {
    try {
      if (!token()) await ensureLocalSession();
      const r = await api("/api/studio/projects");
      state.projects = r.projects || [];
      renderCourseProjects();
      renderProjects();
    } catch (e) {
      if (e.status === 401) {
        $("#course-projects").innerHTML = `<div class="proj"><strong>请先登录</strong><span>回到蓝图首页注册/登录后再回来</span></div>`;
      }
    }
  }
  function renderCourseProjects() {
    const host = $("#course-projects");
    if (!host) return;
    if (!state.projects.length) { host.innerHTML = `<p class="hint">还没有项目。先去首页生成一个方案。</p>`; return; }
    host.innerHTML = state.projects.map((p) => `
      <div class="proj ${p.id === state.projectId ? "on" : ""}" data-id="${p.id}">
        <strong>${esc(p.name)}</strong>
        <span>${p.parts} 个零件${p.hasCourse ? " · 已有课程" : ""}</span>
      </div>`).join("");
    $$(".proj", host).forEach((el) => el.addEventListener("click", () => selectProject(el.dataset.id)));
  }
  async function selectProject(id) {
    state.projectId = id;
    renderCourseProjects();
    $("#btn-generate").disabled = false;
    const p = state.projects.find((x) => x.id === id);
    $("#course-title").textContent = p ? p.name : "项目课";
    $("#course-sub").textContent = p ? (p.description || "按这个项目的真实链路逐步完成。") : "";
    try {
      const r = await api("/api/studio/course/" + id);
      if (r.course) { state.course = r.course; renderCourse(); }
      else { state.course = null; $("#chapters").innerHTML = `<div class="empty big"><div class="empty-mark">▤</div><p>点左侧「生成项目课」，把 ${esc(p?.name || "这个项目")} 变成分步教程。</p></div>`; updateStats(); }
    } catch (e) { toast("读取课程失败：" + e.message); }
  }
  $$("#level-seg button").forEach((b) => b.addEventListener("click", () => {
    $$("#level-seg button").forEach((x) => x.classList.toggle("on", x === b));
    state.level = b.dataset.level;
    if (state.course) toast("学段已切换，点「生成项目课」按新学段重排");
  }));
  $("#btn-generate")?.addEventListener("click", async () => {
    if (!state.projectId) return;
    const btn = $("#btn-generate");
    btn.disabled = true;
    try {
      const r = await api("/api/studio/course/" + state.projectId + "/generate", { method: "POST", body: { level: state.level } });
      state.course = r.course;
      renderCourse();
      toast("课程已生成：" + r.course.title);
    } catch (e) { toast("生成失败：" + e.message); }
    finally { btn.disabled = false; }
  });

  function updateStats() {
    if (!state.course) { $("#stat-chapters").textContent = "—"; $("#stat-steps").textContent = "—"; $("#stat-done").textContent = "0%"; return; }
    const steps = state.course.chapters.flatMap((c) => c.steps);
    const done = steps.filter((s) => s.done).length;
    $("#stat-chapters").textContent = state.course.chapters.length;
    $("#stat-steps").textContent = steps.length;
    $("#stat-done").textContent = (steps.length ? Math.round((done / steps.length) * 100) : 0) + "%";
  }

  function renderCourse() {
    const c = state.course;
    $("#course-title").textContent = c.title;
    $("#course-sub").textContent = c.subtitle + " · " + c.summary;
    const host = $("#chapters");
    host.innerHTML = c.chapters.map((ch, i) => `
      <div class="chapter ${i === 0 ? "open" : ""}" data-ch="${ch.id}">
        <div class="chapter-head">
          <span class="chapter-tag">${esc(ch.stage)}</span>
          <h3>${esc(ch.title)}</h3>
          <em>${ch.steps.length} 步</em>
          <span class="caret">▸</span>
        </div>
        <div class="chapter-intro">${esc(ch.intro || "")}<br><b style="color:#cfd7e1">本章目标：</b>${esc(ch.goal)}</div>
        <div class="chapter-steps">
          ${ch.steps.map((s, j) => `
            <div class="step ${s.done ? "done" : ""} ${i === 0 && j === 0 ? "open" : ""}" data-step="${s.id}">
              <div class="step-top">
                <div class="check ${s.done ? "on" : ""}" data-check="${s.id}">✓</div>
                <div style="flex:1">
                  <h4>${esc(s.title)}</h4>
                  <p class="goal">${esc(s.goal)}</p>
                </div>
                <span class="mins">${s.minutes || 8} min</span>
              </div>
              <div class="step-body">
                <div class="detail">${(Array.isArray(s.detail) ? s.detail : [String(s.detail || "")]).map((d) => `<p>${esc(d)}</p>`).join("")}</div>
                <div class="lists">
                  <div class="list-block"><span>动手任务</span><ul>${(Array.isArray(s.todo) ? s.todo : [String(s.todo || "")]).map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>
                  <div class="list-block"><span>检查点</span><ul>${(Array.isArray(s.check) ? s.check : [String(s.check || "")]).map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>
                </div>
                <div class="step-foot">
                  <button class="mini preview" data-preview="${esc(s.preview ? s.preview.url : "")}">预览 · ${esc(s.preview ? s.preview.label : "项目")}</button>
                  <button class="mini" data-expand="${s.id}">展开/收起</button>
                  <button class="mini" data-ask="${esc(s.title)}">问导师</button>
                </div>
              </div>
            </div>`).join("")}
        </div>
      </div>`).join("");

    $$(".chapter-head", host).forEach((h) => h.addEventListener("click", () => h.parentElement.classList.toggle("open")));
    $$("[data-check]", host).forEach((el) => el.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = el.dataset.check;
      const step = findStep(id);
      const next = !(step && step.done);
      el.classList.toggle("on", next);
      const card = el.closest(".step");
      card.classList.toggle("done", next);
      if (step) step.done = next;
      updateStats();
      try { await api("/api/studio/course/" + c.projectId + "/step", { method: "POST", body: { stepId: id, done: next } }); } catch {}
    }));
    $$("[data-expand]", host).forEach((el) => el.addEventListener("click", (e) => {
      e.stopPropagation();
      el.closest(".step").classList.toggle("open");
    }));
    $$("[data-preview]", host).forEach((el) => el.addEventListener("click", (e) => {
      e.stopPropagation();
      const u = el.dataset.preview;
      if (!u) return;
      window.open(u, "_blank", "noopener");
    }));
    $$("[data-ask]", host).forEach((el) => el.addEventListener("click", (e) => {
      e.stopPropagation();
      $("#course-input").value = "讲讲「" + el.dataset.ask + "」这一步怎么做";
      $("#course-input").focus();
    }));
    $$(".step-top", host).forEach((top) => top.addEventListener("click", () => top.parentElement.classList.toggle("open")));

    updateStats();
    renderChat();
  }
  function findStep(id) {
    if (!state.course) return null;
    for (const c of state.course.chapters) for (const s of c.steps) if (s.id === id) return s;
    return null;
  }

  function renderChat() {
    const log = $("#course-chat");
    if (!log) return;
    const chat = (state.course && state.course.chat) || [];
    log.innerHTML = chat.length
      ? chat.map((m) => `<div class="msg ${m.role === "user" ? "user" : "bot"}">${esc(m.content)}</div>`).join("")
      : `<div class="msg bot">选好项目和学段，我就按这个项目的接线、结构、零件、组装和 3D 产出，一步步带你做。哪里卡住直接问。</div>`;
    log.scrollTop = log.scrollHeight;
  }

  $("#course-send")?.addEventListener("click", () => sendCourse());
  $("#course-input")?.addEventListener("keydown", (e) => { if (e.key === "Enter") sendCourse(); });
  async function sendCourse() {
    const input = $("#course-input");
    const text = input.value.trim();
    if (!text) return;
    if (!state.projectId) return toast("先在左侧选一个项目");
    if (!state.course) return toast("先点「生成项目课」");
    input.value = "";
    const log = $("#course-chat");
    const d = document.createElement("div");
    d.className = "msg user"; d.textContent = text;
    log.appendChild(d); log.scrollTop = log.scrollHeight;
    const typing = document.createElement("div");
    typing.className = "msg bot"; typing.textContent = "…";
    log.appendChild(typing); log.scrollTop = log.scrollHeight;
    try {
      const r = await api("/api/studio/course/" + state.projectId + "/chat", { method: "POST", body: { message: text, level: state.level } });
      state.course = r.course;
      typing.remove();
      if (r.courseChanged) { renderCourse(); toast("课程已按你的要求调整"); }
      else { renderChat(); }
    } catch (e) {
      typing.textContent = "出错了：" + e.message;
    }
  }

  // ---------------- 项目库 ----------------
  function renderProjects() {
    const host = $("#project-grid");
    if (!host) return;
    if (!state.projects.length) {
      host.innerHTML = `<div class="empty big"><div class="empty-mark">▤</div><p>还没有项目。回到首页描述一个想法，生成第一个方案。</p></div>`;
      return;
    }
    host.innerHTML = state.projects.map((p) => `
      <article class="proj-card">
        <span class="label">项目</span>
        <h3>${esc(p.name)}</h3>
        <p>${esc(p.description || "暂无描述")}</p>
        <div class="row">
          <a href="/project/${p.id}" target="_blank" rel="noopener">打开项目</a>
          <button data-course="${p.id}">${p.hasCourse ? "继续课程" : "生成课程"}</button>
        </div>
      </article>`).join("");
    $$("[data-course]", host).forEach((b) => b.addEventListener("click", () => {
      $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === "course"));
      $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-course"));
      state.view = "course";
      const p = state.projects.find((x) => x.id === b.dataset.course);
      selectProject(b.dataset.course);
      if (p && !p.hasCourse) $("#btn-generate").focus();
    }));
  }

  // ---------------- init ----------------
  function applySessionHandoff() {
    const qs = new URLSearchParams(location.search);
    const sid = qs.get("session");
    if (!sid) return;
    const n = Math.max(1, Math.min(8, Number(qs.get("n")) || 4));
    state.sessionId = sid;
    state.previews = Array.from({ length: n }, (_, i) => ({
      index: i,
      seed: i,
      url: PX + "/api/data/" + sid + "/previews/img_" + i + ".png",
    }));
    state.selected = 0;
    renderPreviews();
    const label = $("#session-label");
    if (label) label.textContent = "会话 " + sid;
    const btn = $("#btn-3d");
    if (btn) btn.dataset.hasSession = "1";
    setPipeline(2);
    // The chat may already have produced a real 3D model for this session.
    // Show it instead of asking the user to spend credits twice.
    const existingGlb = PX + "/api/data/" + sid + "/model/mesh.glb";
    fetch(existingGlb, { method: "HEAD" }).then((res) => {
      if (!res.ok) return;
      state.model = { model_url: existingGlb, engine: "tripo3d" };
      $("#model-title").textContent = "模型已生成";
      $("#m-engine").textContent = "tripo3d";
      $("#m-progress").textContent = "完成 · 可下载 STL / GLB";
      $("#m-bar").style.width = "100%";
      $("#btn-glb").style.display = "";
      $("#btn-glb").href = existingGlb;
      $("#btn-glb").setAttribute("download", "model.glb");
      $("#btn-stl").style.display = "";
      $("#btn-stl").href = PX + "/api/data/" + sid + "/model/mesh.stl";
      $("#btn-stl").setAttribute("download", "model.stl");
      $("#btn-fallback").style.display = "none";
      showModel(existingGlb);
      setPipeline(4);
      setTimeout(scrollToModel, 500);
    }).catch(() => {});
    // If this session only has the local 2.5D relief, show it too instead of
    // asking the user to generate the same model again.
    const existingRelief = PX + "/api/data/" + sid + "/model_relief/mesh.glb";
    fetch(existingRelief, { method: "HEAD" }).then((res) => {
      if (!res.ok || state.model) return;
      state.model = { model_url: existingRelief, engine: "cartoon" };
      $("#model-title").textContent = "浮雕模型已生成";
      $("#m-engine").textContent = "本地浮雕";
      $("#m-progress").textContent = "完成 · 可下载 STL / GLB";
      $("#m-bar").style.width = "100%";
      $("#btn-glb").style.display = "";
      $("#btn-glb").href = existingRelief;
      $("#btn-glb").setAttribute("download", "model.glb");
      $("#btn-stl").style.display = "";
      $("#btn-stl").href = PX + "/api/data/" + sid + "/model_relief/mesh.stl";
      $("#btn-stl").setAttribute("download", "model.stl");
      $("#btn-fallback").style.display = "none";
      showModel(existingRelief);
      setPipeline(4);
      setTimeout(scrollToModel, 500);
    }).catch(() => {});
    const view = document.getElementById("view-make");
    if (view) view.classList.add("reveal-preview");
    const banner = $("#session-banner");
    const bannerId = $("#session-banner-id");
    if (banner) banner.style.display = "flex";
    if (bannerId) bannerId.textContent = sid;
    const ta = $("#prompt");
    const p = qs.get("prompt");
    if (ta && p) ta.value = p;
  }

  async function init() {
    await ensureLocalSession();
    renderPreviews();
    refreshStatus();
    loadPresets();
    await loadProjects();
    applySessionHandoff();
    const mode = new URLSearchParams(location.search).get("mode");
    if (mode === "course") {
      const tab = document.querySelector('.tab[data-view="course"]');
      if (tab) tab.click();
      const pid = new URLSearchParams(location.search).get("project");
      if (pid) selectProject(pid);
    }
    setInterval(refreshStatus, 20000);
    if (location.hash === "#3d") { /* 默认就在 3D 视图 */ }
  }
  init();
})();

// ---------- progressive / lean UI (default on) ----------
(() => {
  const body = document.body;
  const leanBtn = document.getElementById("btn-lean");
  const storeKey = "blueai.studio.lean";

  function setLean(on) {
    body.classList.toggle("lean", on);
    if (leanBtn) {
      leanBtn.setAttribute("aria-pressed", on ? "true" : "false");
      leanBtn.textContent = on ? "简洁模式" : "完整模式";
    }
    if (!on) {
      document.querySelectorAll(".copilot.open,.course-list.open").forEach((el) => el.classList.remove("open"));
    }
    try { localStorage.setItem(storeKey, on ? "1" : "0"); } catch {}
  }

  const saved = (() => { try { return localStorage.getItem(storeKey); } catch { return null; } })();
  setLean(saved === null ? true : saved === "1");

  leanBtn && leanBtn.addEventListener("click", () => setLean(!body.classList.contains("lean")));

  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
    body.dataset.view = t.dataset.view || "make";
    document.querySelectorAll(".copilot.open,.course-list.open").forEach((el) => el.classList.remove("open"));
  }));

  const open = (sel) => { const el = document.querySelector(sel); if (el) el.classList.add("open"); };
  const close = (sel) => { const el = document.querySelector(sel); if (el) el.classList.remove("open"); };

  document.getElementById("btn-assist")?.addEventListener("click", () => { close(".course-copilot"); document.querySelector("#view-make .steps")?.classList.remove("open"); open(".copilot"); });
  document.getElementById("btn-assist-close")?.addEventListener("click", () => close(".copilot"));
  document.getElementById("btn-course-assist")?.addEventListener("click", () => open(".course-copilot"));
  document.getElementById("btn-course-assist-close")?.addEventListener("click", () => close(".course-copilot"));
  document.getElementById("btn-projlist")?.addEventListener("click", () => open(".course-list"));

  // Auto-close the drawer when clicking outside it.
  document.addEventListener("pointerdown", (e) => {
    if (!body.classList.contains("lean")) return;
    document.querySelectorAll(".copilot.open,.course-list.open").forEach((el) => {
      if (!el.contains(e.target) && !e.target.closest("#btn-assist,#btn-course-assist,#btn-projlist")) el.classList.remove("open");
    });
  });
})();
// progressive reveal: only show the stage the learner has reached
(() => {
  const view = document.getElementById("view-make");
  if (!view) return;
  const grid = document.getElementById("preview-grid");
  const model = document.getElementById("model-view");
  function sync() {
    const hasPreview = !!grid && grid.querySelectorAll(".preview-item").length > 0;
    const hasModel = !!model && (!!model.querySelector("model-viewer") || !!model.querySelector("img, video") || (document.getElementById("btn-stl")?.style.display !== "none" && document.getElementById("btn-stl")?.style.display !== ""));
    view.classList.toggle("reveal-preview", hasPreview);
    view.classList.toggle("reveal-model", hasModel);
  }
  const obs = new MutationObserver(sync);
  if (grid) obs.observe(grid, { childList: true, subtree: true });
  if (model) obs.observe(model, { childList: true, subtree: true, attributes: true });
  sync();
  setInterval(sync, 1200);
})();
// lean: expose the pipeline / presets drawer on demand
(() => {
  const btn = document.getElementById("btn-steps");
  const steps = document.querySelector("#view-make .steps");
  if (!btn || !steps) return;
  btn.addEventListener("click", () => { const willOpen = !steps.classList.contains("open"); document.querySelectorAll(".copilot.open").forEach((el) => el.classList.remove("open")); steps.classList.toggle("open", willOpen); });
  document.addEventListener("pointerdown", (e) => {
    if (!document.body.classList.contains("lean")) return;
    if (steps.classList.contains("open") && !steps.contains(e.target) && !e.target.closest("#btn-steps")) steps.classList.remove("open");
  });
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => steps.classList.remove("open")));
})();
// ---------- handoff from project chat: ?project=<id>&mode=3d|course ----------
(() => {
  const qs = new URLSearchParams(location.search);
  const mode = qs.get("mode");
  const pid = qs.get("project");
  let hand = {};
  try { hand = JSON.parse(localStorage.getItem("bp.studio.handoff") || "{}"); } catch {}

  if (mode === "3d") {
    const tab = [...document.querySelectorAll(".tab")].find((t) => t.dataset.view === "make");
    if (tab) tab.click();
    const ta = document.getElementById("prompt");
    if (ta && hand.prompt) {
      ta.value = hand.prompt;
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (ta && pid) {
      const head = document.createElement("div");
      head.textContent = hand.prompt
        ? "来自项目的设计 · 已带入对话里的描述，可直接生成预览与 3D 模型"
        : "来自项目的设计 · 先确认描述，再生成预览与 3D 模型";
      head.style.cssText = "font-size:11.5px;color:#0f8a50;background:#e9f8f0;border:1px solid #bfe9d2;border-radius:8px;padding:7px 10px;margin-bottom:12px";
      ta.closest(".prompt-card")?.prepend(head);
    }
  }

  if (mode === "course") {
    const tab = [...document.querySelectorAll(".tab")].find((t) => t.dataset.view === "course");
    if (tab) tab.click();
    let tries = 0;
    const iv = setInterval(() => {
      tries += 1;
      const el = pid ? document.querySelector('.proj[data-id="' + pid + '"]') : null;
      if (el) { el.click(); clearInterval(iv); }
      if (tries > 25) clearInterval(iv);
    }, 400);
    if (pid) {
      const list = document.querySelector(".course-list");
      if (list) list.classList.add("open");
    }
  }
})();
// close the project drawer right after choosing one
document.addEventListener("click", (e) => {
  if (!e.target.closest(".proj")) return;
  setTimeout(() => document.querySelector(".course-list")?.classList.remove("open"), 350);
});