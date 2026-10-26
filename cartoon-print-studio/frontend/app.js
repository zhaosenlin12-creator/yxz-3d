import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFExporter } from "./vendor/three/examples/examples/jsm/exporters/GLTFExporter.js";
import { OBJExporter } from "./vendor/three/examples/examples/jsm/exporters/OBJExporter.js";
import { STLExporter } from "./vendor/three/examples/examples/jsm/exporters/STLExporter.js";
import { initWorkbench, workbenchInternals } from "./workbench.js";

const API = "";
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const state = {
  sid: null,
  previewSessionId: null,
  projectId: null,
  projectName: "",
  currentPrompt: "",
  messages: [],
  previews: [],
  modelVersions: [],
  activeVersionId: null,
  canvasElements: [],
  canvasViewport: { x: 0, y: 0, zoom: 1 },
  selectedIndex: null,
  meshUrl: null,
  meshSeed: 42,
  three: null,
  selectedObject: null,
  undoStack: [],
  projectPrimitives: [],
  exploded: false,
  xray: false,
  sceneSource: null,
  sceneId: null,
  sceneRecord: null,
  sceneUploading: false,
  sceneTrainerConfigured: false,
  sceneBuildTimer: null,
  sceneStatusTimer: null,
  saveTimer: null,
  saving: false,
  geometryDirty: false,
};

function show(step) {
  $$(".step").forEach(el => el.classList.remove("active"));
  if (step) $(step).classList.add("active");
}
function setStatus(t) { $("#status").textContent = t; }
function setLoader(on, text) {
  $("#loader-text").textContent = text || "";
  // Reset progress when loader opens
  if (on) setProgress(0, "");
  $("#loader").classList.toggle("hidden", !on);
  if (text) $("#loader-text").textContent = text;
  if (!on) $("#think-feed").innerHTML = "";
}

function setBuildPreview(src) {
  const img = document.getElementById("build-preview-img");
  const stage = document.getElementById("build-stage");
  if (img && src) img.src = src;
  if (stage) stage.style.setProperty("--build-progress", "8%");
  document.querySelectorAll(".build-steps span").forEach(step => step.classList.remove("active"));
  document.getElementById("build-step-shape")?.classList.add("active");
}
let _progressPollTimer = null;
let _progressLastTs = 0;

function feed(msg) {
  const feed = $("#think-feed");
  if (!feed) return;
  const line = document.createElement("div");
  line.className = "think-line";
  line.textContent = msg;
  feed.appendChild(line);
  feed.scrollTop = feed.scrollHeight;
}

// slider bind
const slider = $("#n-slider");
const badge = $("#n-badge");
slider.addEventListener("input", () => { badge.textContent = slider.value; });

// chip binds
$$(".ex-chip").forEach(el => {
  el.addEventListener("click", () => {
    $("#prompt").value = el.dataset.prompt;
    $("#prompt").focus();
  });
});

$("#btn-preview").addEventListener("click", startPreview);
$("#prompt").addEventListener("input", scheduleProjectSave);
$("#btn-demo").addEventListener("click", startDemoExperience);
$("#btn-redo").addEventListener("click", () => {
  show("#step-prompt");
  setStatus("就绪");
});
$("#btn-make-3d").addEventListener("click", generate3D);
$("#btn-back-pick").addEventListener("click", () => {
  disposeThree();
  show("#step-pick");
  setStatus("挑一张");
});
$("#btn-print").addEventListener("click", printModel);
$("#btn-print-again").addEventListener("click", () => location.reload());
$("#btn-export").addEventListener("click", exportModel);
$("#btn-export-stl").addEventListener("click", () => downloadModel("stl"));
$("#btn-export-obj").addEventListener("click", () => downloadModel("obj"));
$("#btn-export-glb").addEventListener("click", () => downloadModel("glb"));

// 3D 工作台：素材、选中编辑、作品库
$$('[data-primitive]').forEach(btn => btn.addEventListener('click', () => addPrimitive(btn.dataset.primitive)));
$("#edit-x").addEventListener("input", syncInspectorToObject);
$("#edit-z").addEventListener("input", syncInspectorToObject);
$("#edit-scale").addEventListener("input", syncInspectorToObject);
[$("#edit-x"), $("#edit-z"), $("#edit-scale")].forEach(input => input.addEventListener("change", endInspectorEdit));
$$('.swatch').forEach(btn => btn.addEventListener('click', () => setSelectedColor(btn.dataset.color)));
$("#btn-duplicate").addEventListener("click", duplicateSelected);
$("#btn-delete").addEventListener("click", deleteSelected);
$("#btn-undo").addEventListener("click", undoLastAction);
$("#btn-save-project").addEventListener("click", saveProject);
$("#project-name").addEventListener("input", scheduleProjectSave);
$("#btn-reset-camera").addEventListener("click", resetCamera);
$("#btn-explode").addEventListener("click", toggleExplodedView);
$("#btn-xray").addEventListener("click", toggleXrayView);
$("#explode-range").addEventListener("input", (event) => setExplosionFactor(Number(event.target.value)));
$("#btn-library").addEventListener("click", openLibrary);
$("#btn-close-library").addEventListener("click", closeLibrary);
$("#drawer-backdrop").addEventListener("click", closeLibrary);
$("#btn-scene-mode").addEventListener("click", openSceneMode);
$("#btn-close-scene").addEventListener("click", closeSceneMode);
$("#btn-scene-start").addEventListener("click", startSceneExperience);
$("#btn-scene-submit").addEventListener("click", submitSceneToCloud);
$("#scene-captures").addEventListener("change", () => {
  state.sceneId = null;
  state.sceneRecord = null;
  state.sceneUploading = false;
  disposeSceneExperience();
  updateSceneCaptureSelection();
});
$("#scene-asset").addEventListener("change", importSceneAsset);
document.addEventListener("keydown", (event) => {
  if ((event.key === "Delete" || event.key === "Backspace") && state.selectedObject) deleteSelected();
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); undoLastAction(); }
});

migrateLegacyProjects();

async function startPreview() {
  const prompt = $("#prompt").value.trim();
  if (!prompt) { alert("请输入描述"); return; }
  state.selectedIndex = null;
  state.currentPrompt = prompt;
  state.messages.push({ role: "user", content: prompt, createdAt: Date.now() });
  scheduleProjectSave();
  const thinkOn = $("#think-toggle").checked;
  const n = parseInt($("#n-slider").value, 10);

  $("#btn-preview").disabled = true;
  setLoader(true, thinkOn ? `AI 思考 + 出图（${n} 张）...` : `本地 SD 出图（${n} 张）...`);
  feed("收到需求：" + prompt);
  setStatus("生成预览...");

  try {
    let res, data;
    // Generate a session_id client-side so progress polling can begin
    // immediately while the backend processes the heavy work.
    const mySid = (crypto && crypto.randomUUID)
      ? crypto.randomUUID().replace(/-/g, '').slice(0, 12)
      : Math.random().toString(16).slice(2, 14);
    state.previewSessionId = mySid;
    startProgressPolling(mySid);

    if (thinkOn) {
      feed("调用多模态 LLM 拆解需求 / 规则增强...");
      const r = await fetch(API + "/api/previews_v2", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, n, prefer: "aixj", session_id: mySid }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      data = await r.json();
    } else {
      const r = await fetch(API + "/api/previews", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, n, session_id: mySid }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      data = await r.json();
    }
    // Synchronous previews returned? Show them right away.
    if (data.previews && data.previews.length) {
      (data.thinking || []).forEach(t => feed(t));
      state.previews = data.previews.map(preview => ({ ...preview, session_id: mySid }));
      renderThinking(data);
      renderPreviews();
      show("#step-pick");
    } else {
      // Async path: poll the worker via progress endpoint until done, then fetch the result.
      feed("后端开始处理，等待出图...");
      await waitForPreviews(mySid);
      renderThinking(state._lastPreviewsData || {});
      state.previews = (state._lastPreviewsData?.previews || []).map(preview => ({ ...preview, session_id: mySid }));
      renderPreviews();
      show("#step-pick");
    }
    setStatus(`已生成 ${state.previews.length} 张预览`);
    state.messages.push({ role: "assistant", content: `已生成 ${state.previews.length} 张预览，请选择一个方案继续。`, createdAt: Date.now() });
    scheduleProjectSave();
  } catch (e) {
    alert("生成失败：" + e.message);
    setStatus("出错了");
  } finally {
    stopProgressPolling();
    $("#btn-preview").disabled = false;
    setLoader(false);
  }
}

async function startDemoExperience() {
  const button = $("#btn-demo");
  if (button) button.disabled = true;
  setStatus("正在打开本机示例...");
  try {
    const r = await fetch(API + "/api/demo");
    if (!r.ok) throw new Error("本机没有可用示例模型");
    const demo = await r.json();
    state.sid = demo.session_id;
    state.previewSessionId = demo.session_id;
    state.meshUrl = demo.model_url;
    state.projectId = null;
    state.modelVersions = [{
      id: demo.session_id, sid: demo.session_id, meshUrl: demo.model_url,
      engine: "demo", prompt: demo.prompt || "", createdAt: Date.now(), primitives: [],
    }];
    state.activeVersionId = demo.session_id;
    state.meshSeed = "demo";
    state.selectedIndex = 0;
    state.previews = demo.preview_url ? [{ path: demo.preview_url, caption: "本机示例 · 蓝色小英雄" }] : [];
    $("#btn-print").disabled = false;
    $("#project-name").value = "我的第一个 AI 小英雄";
    $("#save-state").textContent = "示例体验，可继续编辑";
    $("#model-info").innerHTML = `<b>本机示例模型</b> · 已准备好编辑、导出和打印`;
    show("#step-3d");
    initThree(state.meshUrl);
    renderModelVersions();
    await refreshPrintability(demo.session_id);
    setStatus("示例已打开");
  } catch (e) {
    alert("示例打开失败：" + e.message);
    setStatus("示例不可用");
  } finally {
    if (button) button.disabled = false;
  }
}

function renderThinking(data) {
  const box = $("#thinking-content");
  if (!box) return;
  let html = "";
  if (data.thinking && data.thinking.length) {
    html += "<ol>";
    data.thinking.forEach(t => { html += `<li>${escapeHtml(t)}</li>`; });
    html += "</ol>";
  }
  if (data.think_source) {
    html += `<div class="think-meta">策略来源：<b>${escapeHtml(data.think_source)}</b>`;
    if (data.think_model) html += ` · 模型：${escapeHtml(data.think_model)}`;
    if (data.image_source) html += ` · 图片来源：<b>${escapeHtml(data.image_source)}</b>`;
    if (data.elapsed_ms) html += ` · 耗时：${(data.elapsed_ms/1000).toFixed(1)}s`;
    html += "</div>";
  }
  box.innerHTML = html || "<i>无思考轨迹</i>";
}

function renderPreviews() {
  const grid = $("#grid");
  grid.innerHTML = "";
  state.previews.forEach((p, i) => {
    const tile = document.createElement("div");
    tile.className = "tile";
    tile.innerHTML = `
      <img src="${p.b64 ? `data:image/png;base64,${p.b64}` : escapeHtml(p.path || "")}" alt="${escapeHtml(p.caption || `预览 ${i + 1}`)}">
      <div class="lbl">${escapeHtml(p.caption || ("图 " + (i + 1)))}</div>`;
    if (p.sub_prompt) tile.title = p.sub_prompt;
    tile.addEventListener("click", () => {
      $$(".tile").forEach(t => t.classList.remove("selected"));
      tile.classList.add("selected");
      state.selectedIndex = i;
      state.previewSessionId = p.session_id || sessionIdFromPath(p.path) || state.previewSessionId;
      $("#btn-make-3d").disabled = false;
      scheduleProjectSave();
    });
    grid.appendChild(tile);
  });
}

function sessionIdFromPath(path) {
  return String(path || "").match(/^\/api\/data\/([A-Za-z0-9_-]+)\//)?.[1] || null;
}

async function generate3D() {
  if (state.selectedIndex == null) return;
  $("#btn-make-3d").disabled = true;
  try {
  // Engine dispatch:
  //   hunyuan: local open-source high-quality shape generation, no per-call fee.
  //   cartoon: multi-layer relief, fast and reliable offline fallback.
  //   multi: TripoSR with multi-view fusion (front + 3/4 side).
  //   tripo3d: optional cloud PBR path, only when explicitly selected.
  const engine = (document.querySelector("input[name=\"engine\"]:checked") || {}).value || "tripo3d";
    const selectedPreview = state.previews[state.selectedIndex];
    const sourceSessionId = state.previewSessionId || state.sid;
    const forkResponse = await fetch(`${API}/api/session/${encodeURIComponent(sourceSessionId)}/fork`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_index: state.selectedIndex }),
    });
    if (!forkResponse.ok) throw new Error("无法建立独立模型版本，请检查选中的预览");
    const fork = await forkResponse.json();
    state.sid = fork.session_id;
    const previewSource = selectedPreview?.b64 ? `data:image/png;base64,${selectedPreview.b64}` : selectedPreview?.path;
    state.sceneSource = previewSource || state.sceneSource;
    setBuildPreview(previewSource);
    if (engine === "tripo3d") {
        // ---- Tripo3D cloud image-to-3D path ----
        startProgressPolling(state.sid);
        setLoader(true, "Tripo 生成中…");
        feed("调用 Tripo 云端建模");
        setStatus("Tripo 生成中…");
        try {
          const r = await fetch(API + "/api/3d_tripo", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: state.sid,
              image_index: state.selectedIndex,
              target_height_mm: 70,
              model_version: "v3.1-20260211",
              texture_quality: "detailed",
            }),
          });
          if (!r.ok) {
            const errText = await r.text().catch(() => "");
            throw new Error("HTTP " + r.status + " " + errText.slice(0, 200));
          }
          const data = await r.json();
          setGeneratedVersion(data, engine, sourceSessionId, state.selectedIndex);
          $("#btn-print").disabled = false;
          setLoader(false);
          initThree(state.meshUrl);
          $("#model-info").innerHTML = "<b>模型已准备好</b> · 可以继续编辑或导出打印";
          setStatus("Tripo 准备好了");
          return;
        } catch (e) {
          feed(e.message.includes("额度不足") ? "⚠️ Tripo 额度不足" : "⚠️ Tripo 未完成，改用卡通浮雕");
          // fall through to cartoon
        }
      }
      if (engine === "multi") {
    // ---- Multi-view TripoSR path ----
    startProgressPolling(state.sid);
    setLoader(true, "多视角 3D 重建中（生成 3/4 侧视图约 30 秒 + 重建约 90 秒）...");
    feed("调用多视角路径：先补一张 3/4 侧视图，再让 TripoSR 融合重建");
    setStatus("生成 3D 中（多视角模式）...");
    try {
      const r = await fetch(API + "/api/3d_v2", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: state.sid, image_index: state.selectedIndex, views: 1 }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const data = await r.json();
      setGeneratedVersion(data, engine, sourceSessionId, state.selectedIndex);
      $("#btn-print").disabled = false;
      state.meshSeed = "multi";
      feed("多视角 mesh 落地: " + data.model_url + "（" + data.faces.toLocaleString() + " 面，" + (data.views_used || data.view_count || 2) + " 视图融合）");
      show("#step-3d");
      $("#model-info").innerHTML = "<b>模型已准备好</b> · 可以继续编辑或导出打印";
      initThree(state.meshUrl);
      setStatus("3D 准备好了（多视角模式）");
      return;
    } catch (e) {
      feed("⚠️ 多视角失败: " + e.message + "，回落到 Hunyuan");
      // fall through to HY
    }
  }
  if (engine === "hunyuan" || engine === "hy") {
    // ---- Hunyuan3D-2 mini local open-source path ----
    startProgressPolling(state.sid);
    setLoader(true, "本地 Hunyuan3D-2 mini 重建中（首次运行需要加载模型）...");
    feed("调用 Hunyuan3D-2 mini（本地开源，不消耗 Tripo3D 额度）");
    setStatus("本地生成 3D 中（高质量模式）...");
    try {
      const r = await fetch(API + "/api/3d_hy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // Balanced preset for 6GB GPUs: cleaner than the fast fallback while
        // keeping first-time student runs within VRAM.
        body: JSON.stringify({ session_id: state.sid, image_index: state.selectedIndex, steps: 6, octree: 112 }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const data = await r.json();
      setGeneratedVersion(data, engine, sourceSessionId, state.selectedIndex);
      $("#btn-print").disabled = false;
      state.meshSeed = "hunyuan";
      feed("Hunyuan mesh 落地: " + data.model_url + "（" + data.faces.toLocaleString() + " 面）");
      show("#step-3d");
      $("#model-info").innerHTML = "<b>模型已准备好</b> · 可以继续编辑或导出打印";
      initThree(state.meshUrl);
      setStatus("3D 准备好了（Hunyuan 高质）");
      return;
    } catch (e) {
      feed("⚠️ Hunyuan 失败: " + e.message + "，回落到本地卡通浮雕");
      // fall through to local cartoon path
    }
  }
  // Cartoon-optimized multi-layer relief (default path for cute cartoon characters).
  if (engine !== "cartoon") {
    alert("未知引擎: " + engine + "，回落到卡通浮雕");
  }
  startProgressPolling(state.sid);
  setLoader(true, "正在构建卡通 3D 浮雕...");
  feed("调用卡通浮雕路径（多层 3D 模型）");
  setStatus("生成 3D 中（卡通模式）...");
  try {
    const r = await fetch(API + "/api/3d_cartoon", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sid, image_index: state.selectedIndex, layers: 6, layer_step_mm: 4.0, base_mm: 2.0, target_side: 384 }),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    setGeneratedVersion(data, "cartoon", sourceSessionId, state.selectedIndex);
      $("#btn-print").disabled = false;
    state.meshSeed = "cartoon";
    feed("卡通浮雕 mesh: " + data.model_url + "（" + data.faces.toLocaleString() + " 面，" + data.layers + " 层）");
    show("#step-3d");
    $("#model-info").innerHTML = "<b>模型已准备好</b> · 可以继续编辑或导出打印";
    initThree(state.meshUrl);
    setStatus("3D 准备好了（卡通浮雕模式）");
    return;
  } catch (e) {
    alert("卡通浮雕失败，回落到 TripoSR：" + e.message);
  }
  // Fallback: TripoSR single-view
  startProgressPolling(state.sid);
  setLoader(true, "TripoSR 重建 3D（约 25 秒）...");
  feed("回落到 TripoSR 单图重建");
  setStatus("生成 3D 中...");
  try {
    const r = await fetch(API + "/api/3d", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sid, image_index: state.selectedIndex, seed: 42 }),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    setGeneratedVersion(data, "triposr", sourceSessionId, state.selectedIndex);
      $("#btn-print").disabled = false;
    state.meshSeed = 42;
    feed("TripoSR mesh: " + data.model_url);
    show("#step-3d");
    $("#model-info").innerHTML = "<b>模型已准备好</b> · 可以继续编辑或导出打印";
    initThree(state.meshUrl);
    setStatus("3D 准备好了（TripoSR 模式）");
  } catch (e) {
    alert("3D 生成失败：" + e.message);
    setStatus("出错了");
  } finally {
    $("#btn-make-3d").disabled = false;
    setLoader(false);
  }
  } catch (e) {
    /* outer fallback */
    alert("3D 生成失败：" + e.message);
    setStatus("出错了");
  } finally {
    $("#btn-make-3d").disabled = false;
    setLoader(false);
  }
}

function setGeneratedVersion(data, engine, sourceSessionId, imageIndex) {
  state.meshUrl = data.model_url;
  const version = {
    id: state.sid,
    sid: state.sid,
    sourceSessionId,
    imageIndex,
    prompt: state.currentPrompt,
    engine,
    meshUrl: data.model_url,
    createdAt: Date.now(),
    primitives: [],
  };
  state.modelVersions.push(version);
  state.activeVersionId = version.id;
  renderModelVersions();
  scheduleProjectSave();
}

// Engine endpoints and their fallback chains. The payloads mirror the ones
// used by the step-by-step wizard so both entry points behave the same.
const ENGINE_STEPS = {
  tripo3d: ["/api/3d_tripo", { target_height_mm: 70, model_version: "v3.1-20260211", texture_quality: "detailed" }],
  multi: ["/api/3d_v2", { views: 1 }],
  hunyuan: ["/api/3d_hy", { steps: 6, octree: 112 }],
  cartoon: ["/api/3d_cartoon", { layers: 6, layer_step_mm: 4.0, base_mm: 2.0, target_side: 384 }],
  triposr: ["/api/3d", { seed: 42 }],
};
const ENGINE_CHAINS = {
  tripo3d: ["tripo3d", "cartoon", "triposr"],
  multi: ["multi", "hunyuan", "cartoon", "triposr"],
  hunyuan: ["hunyuan", "cartoon", "triposr"],
  hy: ["hunyuan", "cartoon", "triposr"],
  cartoon: ["cartoon", "triposr"],
  triposr: ["triposr", "cartoon"],
};

/**
 * Run one image-to-3D job and register the result as a new model version.
 *
 * Every run gets its own session so an older version is never overwritten.
 */
async function generateModel({ sessionId, imageIndex = 0, engine = "cartoon", prompt = "", report = () => {}, fork = true }) {
  if (!sessionId) throw new Error("缺少建模输入");
  let sid = sessionId;
  const sourceSessionId = sessionId;
  if (fork) {
    const response = await fetch(`${API}/api/session/${encodeURIComponent(sessionId)}/fork`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_index: imageIndex }),
    });
    if (!response.ok) throw new Error("无法建立独立模型版本，请检查选中的预览");
    const forked = await response.json();
    sid = forked.session_id;
  }
  const chain = ENGINE_CHAINS[engine] || ENGINE_CHAINS.cartoon;
  let lastError = null;
  for (const step of chain) {
    const [path, extra] = ENGINE_STEPS[step];
    report(`正在生成 3D 模型（${step}）…`);
    try {
      const response = await fetch(API + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sid, image_index: imageIndex, ...extra }),
      });
      if (!response.ok) {
        const detail = await response.text().catch(() => "");
        throw new Error(`HTTP ${response.status} ${detail.slice(0, 160)}`);
      }
      const data = await response.json();
      state.sid = sid;
      state.selectedIndex = imageIndex;
      if (prompt) state.currentPrompt = prompt;
      setGeneratedVersion(data, step, sourceSessionId, imageIndex);
      $("#btn-print").disabled = false;
      return { engine: step, data, sid, version: state.modelVersions[state.modelVersions.length - 1] };
    } catch (error) {
      lastError = error;
      report(`${step} 失败：${error.message}`);
    }
  }
  throw lastError || new Error("3D 生成失败");
}

async function printModel() {
  if (!state.meshUrl) return;
  $("#btn-print").disabled = true;
  setLoader(true, "正在导出当前编辑结果并打开 Bambu Studio...");
  try {
    await persistEditedModel();
    const seed = (typeof state.meshSeed === "number") ? state.meshSeed : undefined;
    const r = await fetch(API + "/api/print", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sid, seed }),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    setStatus(data.method === "exe" ? "已发送到 Bambu Studio" : "Bambu 没找到，用系统默认方式打开");
    if (data.error) alert("提示：" + data.error);
    show("#step-print");
  } catch (e) {
    alert("打印启动失败：" + e.message + "\n可手动打开 STL：" + state.meshUrl.replace("/api/data/", "data/").replace("/mesh.glb", "/mesh.stl"))
  } finally {
    $("#btn-print").disabled = false;
    setLoader(false);
  }
}

// ------------------------------------------------------------------
// Export the current 3D model as STL or OBJ (no printer required)
// ------------------------------------------------------------------
async function downloadModel(fmt) {
  if (!state.sid || !state.meshUrl) { alert("还没有模型可以导出"); return; }
  if (!["stl", "obj", "glb"].includes(fmt)) return;
  const button = document.getElementById(`btn-export-${fmt}`);
  if (button) button.disabled = true;
  setStatus(`正在合并 3D 编辑结果并准备 ${fmt.toUpperCase()}...`);
  try {
    await persistEditedModel();
    const r = await fetch(`/api/export/${state.sid}/${fmt}`);
    if (!r.ok) {
      const t = await r.text().catch(() => "");
      throw new Error("HTTP " + r.status + " " + t.slice(0, 160));
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cartoon-model-${state.sid}.${fmt}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    feed("✓ 已导出 " + a.download);
    setStatus("已导出 " + a.download);
  } catch (e) {
    alert("导出失败：" + e.message);
    setStatus("导出失败");
  } finally {
    if (button) button.disabled = false;
  }
}

async function persistEditedModel() {
  if (!_editorGroup || !state.sid) throw new Error("3D 场景还没有加载完成");
  const exportRoot = new THREE.Group();
  exportRoot.add(_editorGroup.clone(true));
  exportRoot.rotation.x = Math.PI / 2;
  exportRoot.updateMatrixWorld(true);

  const stl = new STLExporter().parse(exportRoot, { binary: true });
  const obj = new OBJExporter().parse(exportRoot);
  const glb = await new GLTFExporter().parseAsync(exportRoot, {
    binary: true,
    onlyVisible: true,
  });
  const body = new FormData();
  body.append("stl", new Blob([stl], { type: "model/stl" }), "mesh.stl");
  body.append("obj", new Blob([obj], { type: "text/plain" }), "mesh.obj");
  body.append("glb", new Blob([glb], { type: "model/gltf-binary" }), "mesh.glb");
  const response = await fetch(`${API}/api/session/${encodeURIComponent(state.sid)}/edited-model`, {
    method: "PUT",
    body,
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`当前模型文件未更新：HTTP ${response.status} ${detail.slice(0, 180)}`);
  }
  const result = await response.json();
  state.geometryDirty = false;
  const activeVersion = state.modelVersions.find(version => version.id === state.activeVersionId);
  if (activeVersion) activeVersion.primitives = capturePrimitiveState();
  document.getElementById("model-info").textContent =
    `已导出当前场景 · ${result.faces.toLocaleString()} 面 · ${result.extents_mm.map(n => n.toFixed(0)).join(" × ")} mm`;
  await refreshPrintability(state.sid);
  scheduleProjectSave();
  return result;
}

function canPersistEditedModel() {
  return Boolean(_editorGroup && state.sid);
}

async function exportModel() {
  if (!state.sid || !state.meshUrl) { alert("还没有模型可以导出"); return; }
  const sid = state.sid;
  // We have GLB on the server; STL/OBJ share the same filename pattern.
  // Let user pick the format.
  const choice = prompt("导出格式？\n1 = STL（打印用）\n2 = OBJ（编辑用）\n3 = GLB（带贴图）", "1");
  if (!choice) return;
  const map = { "1": "stl", "2": "obj", "3": "glb" };
  const fmt = map[choice.trim()];
  if (!fmt) { alert("无效选择"); return; }
  await downloadModel(fmt);
}


// ------------------------------------------------------------------
// Bambu Studio path banner — fetched once on page load
// ------------------------------------------------------------------
async function refreshBambuBanner() {
  const banner = document.getElementById("bambu-banner");
  if (!banner) return;
  try {
    const r = await fetch(API + "/api/bambu");
    const j = await r.json();
    if (j.found) {
      banner.innerHTML = `✅ 检测到 Bambu Studio：<code>${j.path}</code>`;
      banner.className = "bambu-banner bambu-ok";
    } else {
      banner.innerHTML = `⚠️ 未找到 Bambu Studio，导出 STL 后用任意切片软件打开。<br>设置路径：在浏览器执行 <code>fetch('/api/bambu',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:'C:\\\\Program Files\\\\Bambu Studio\\\\bambu-studio.exe'})})</code> 后刷新。`;
      banner.className = "bambu-banner bambu-warn";
    }
  } catch (e) {
    banner.textContent = "Bambu 检测失败：" + e.message;
    banner.className = "bambu-banner bambu-warn";
  }
}

async function refreshEngineOptions() {
  try {
    const r = await fetch(API + "/api/engines");
    if (!r.ok) throw new Error("engine discovery failed");
    const data = await r.json();
    const available = new Map((data.engines || []).map(item => [item.id, item]));
    document.querySelectorAll('input[name="engine"]').forEach(input => {
      const info = available.get(input.value);
      const label = input.closest("label");
      if (!info) return;
      input.disabled = !info.available;
      label?.classList.toggle("unavailable", !info.available);
      const hint = label?.querySelector(".hint");
      if (hint) {
        if (input.value === "tripo3d") {
          hint.hidden = true;
          hint.textContent = "";
        } else if (!info.available && !hint.textContent.includes("当前机器不可用")) {
          hint.textContent += " · 当前机器不可用";
        }
      }
    });
    const localPreferred = available.get("hunyuan");
    if (localPreferred?.available) {
      const radio = document.querySelector('input[name="engine"][value="hunyuan"]');
      if (radio) radio.checked = true;
    } else {
      const fallback = available.get("tripo3d")?.available ? "tripo3d" : "cartoon";
      const radio = document.querySelector(`input[name="engine"][value="${fallback}"]`);
      if (radio) radio.checked = true;
    }
    if (data.gpu) feed(`本地 GPU：${data.gpu} · 已优先使用开源本地模型`);
  } catch (e) {
    // Keep the static options usable if discovery is unavailable.
  }
}



function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[m]));
}

async function refreshPrintability(sid) {
  const banner = document.getElementById("print-guide");
  const text = document.getElementById("print-guide-status");
  if (!text || !sid) return;
  text.textContent = "正在检查网格是否适合打印…";
  try {
    const r = await fetch(`${API}/api/printability/${sid}`);
    if (!r.ok) throw new Error("preflight unavailable");
    const result = await r.json();
    if (result.ready) {
      text.textContent = `打印检查通过 · ${result.faces.toLocaleString()} 面 · ${result.extents_mm.map(n => n.toFixed(0)).join(" × ")} mm；STL 适合送入 Bambu Studio。`;
      if (banner) banner.className = "print-guide print-ready";
    } else {
      text.textContent = `打印预检提醒：${(result.warnings || []).join("；") || "建议打印前在切片软件中检查"}。仍可导出，建议在 Bambu Studio 中确认切片。`;
      if (banner) banner.className = "print-guide print-warn";
    }
  } catch (e) {
    text.textContent = "已生成 STL；打印前请在 Bambu Studio 中做最后切片检查。";
  }
}


// ------------------------------------------------------------------
// Three.js viewer (in-page, no separate window)
// ------------------------------------------------------------------
let _threeRenderer = null;
let _threeScene = null;
let _threeCamera = null;
let _threeCtrl = null;
let _threeObj = null;
let _threeAnimating = false;
let _editorGroup = null;
let _editableNodes = [];
let _selectionHelper = null;
let _raycaster = null;
let _pointer = null;
let _threeCanvas = null;
let _explodeParts = [];
let _explodeFactor = 0;
let _explodeTarget = 0;
let _cameraHome = null;

function initThree(url, savedPrimitives = []) {
  disposeThree();
  state.geometryDirty = false;
  const host = document.getElementById("viewer");
  if (!host) { console.error("viewer host missing"); return; }
  host.innerHTML = "";
  const canvas = document.createElement("canvas");
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  canvas.style.display = "block";
  host.appendChild(canvas);
  _threeCanvas = canvas;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  const w = host.clientWidth || 800;
  const h = host.clientHeight || 500;
  renderer.setSize(w, h, false);
  renderer.setClearColor(0xfafbff, 1);

  const scene = new THREE.Scene();
  scene.add(new THREE.AmbientLight(0xffffff, 1.0));
  const d1 = new THREE.DirectionalLight(0xffffff, 1.0); d1.position.set(80, 200, 100); scene.add(d1);
  const d2 = new THREE.DirectionalLight(0xffffff, 0.5); d2.position.set(-80, 100, -100); scene.add(d2);
  scene.add(new THREE.GridHelper(200, 20, 0xddaabb, 0xddaabb));
  _editorGroup = new THREE.Group();
  _editorGroup.name = "卡通小世界";
  scene.add(_editorGroup);
  _editableNodes = [];
  state.undoStack = [];
  _raycaster = new THREE.Raycaster();
  _pointer = new THREE.Vector2();
  canvas.addEventListener("pointerdown", handleCanvasPointer);

  const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 5000);
  camera.position.set(180, 140, 180);
  const ctrl = new OrbitControls(camera, canvas);
  ctrl.target.set(0, 50, 0);
  ctrl.update();
  _cameraHome = { position: camera.position.clone(), target: ctrl.target.clone() };
  _explodeParts = [];
  _explodeFactor = 0;
  _explodeTarget = 0;

  const loader = new GLTFLoader();
  loader.load(
    url,
    (gltf) => {
      _threeObj = gltf.scene;
      // Print exports are Z-up; Three.js displays scenes Y-up. Rotate only
      // this viewer node so the print bed stays horizontal without changing
      // the STL/OBJ/GLB files students export.
      _threeObj.rotation.x = -Math.PI / 2;
      _threeObj.userData.editable = true;
      _threeObj.userData.kind = "model";
      _threeObj.traverse((node) => {
        if (node.isMesh) {
          if (looksLikeBackdrop(node)) node.visible = false;
          // Use vertex colors from the GLB when present, otherwise fall back to pink.
          const hasVertexColor = node.geometry && node.geometry.attributes && node.geometry.attributes.color !== undefined;
          node.material = new THREE.MeshStandardMaterial({
            vertexColors: hasVertexColor,
            color: hasVertexColor ? 0xffffff : 0xffb3d1,
            roughness: 0.6, metalness: 0.05, flatShading: false,
          });
        }
      });
      const box = new THREE.Box3().setFromObject(_threeObj);
      const size = box.getSize(new THREE.Vector3()).length() || 1;
      const c = box.getCenter(new THREE.Vector3());
      _threeObj.position.x -= c.x;
      _threeObj.position.z -= c.z;
      _threeObj.position.y -= box.min.y;
      const scale = 120 / size;
      _threeObj.scale.setScalar(scale);
      _editorGroup.add(_threeObj);
      _editableNodes.push(_threeObj);
      buildExplodeParts(_threeObj);
      updateExplodeStatus();
      savedPrimitives.forEach(descriptor => addPrimitive(descriptor.kind, descriptor, false));
      setStatus("3D 已加载，可以拖动旋转");
    },
    undefined,
    (err) => {
      console.error("GLB load error", err);
      setStatus("GLB 加载失败: " + (err && err.message ? err.message : err));
    }
  );

  const onResize = () => {
    if (!host.isConnected) return;
    const nw = host.clientWidth || 800;
    const nh = host.clientHeight || 500;
    renderer.setSize(nw, nh, false);
    camera.aspect = nw / nh;
    camera.updateProjectionMatrix();
  };
  window.addEventListener("resize", onResize);

  const animate = () => {
    if (!_threeAnimating) return;
    requestAnimationFrame(animate);
    ctrl.update();
    if (Math.abs(_explodeFactor - _explodeTarget) > 0.005) {
      _explodeFactor += (_explodeTarget - _explodeFactor) * 0.16;
      applyExplosionFactor(_explodeFactor);
    }
    if (_selectionHelper) _selectionHelper.update();
    renderer.render(scene, camera);
  };
  _threeRenderer = renderer; _threeScene = scene; _threeCamera = camera; _threeCtrl = ctrl;
  _threeAnimating = true;
  animate();
  if (state.sid) refreshPrintability(state.sid);
}

function looksLikeBackdrop(node) {
  if (!node?.geometry) return false;
  node.geometry.computeBoundingBox();
  const size = node.geometry.boundingBox?.getSize(new THREE.Vector3());
  if (!size) return false;
  const dims = [size.x, size.y, size.z].sort((a, b) => a - b);
  // A renderer backdrop is usually a large, almost paper-thin plane.
  return dims[0] < 1.8 && dims[1] > 45 && dims[2] > 60;
}

function disposeThree() {
  _threeAnimating = false;
  if (_threeCtrl) { try { _threeCtrl.dispose(); } catch (e) {} _threeCtrl = null; }
  if (_threeRenderer) {
    try {
      _threeRenderer.dispose();
      const c = _threeRenderer.domElement;
      if (c && c.parentNode) c.parentNode.removeChild(c);
    } catch (e) {}
    _threeRenderer = null;
  }
  _threeScene = null; _threeCamera = null; _threeObj = null;
  if (_threeCanvas) {
    _threeCanvas.removeEventListener("pointerdown", handleCanvasPointer);
    _threeCanvas = null;
  }
  _editorGroup = null; _editableNodes = []; _selectionHelper = null; _raycaster = null; _pointer = null;
  _explodeParts = []; _explodeFactor = 0; _explodeTarget = 0; _cameraHome = null;
  state.xray = false;
  document.getElementById("btn-xray")?.classList.remove("active");
  state.selectedObject = null;
  updateInspector();
  const host = document.getElementById("viewer");
  if (host) host.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#aaa;">加载中...</div>';
}

function disposeSceneExperience() {
  stopSceneBuildPreview();
  stopSceneStatusPolling();
  const host = document.getElementById("scene-viewer");
  if (host) host.innerHTML = '<div class="scene-empty"><span class="scene-loader-dot"></span><b>准备创建真实场景</b><small>先上传环绕照片或一段视频</small></div><div id="scene-build" class="scene-build hidden" aria-live="polite"></div>';
}

function stopSceneBuildPreview() {
  if (state.sceneBuildTimer) {
    clearInterval(state.sceneBuildTimer);
    state.sceneBuildTimer = null;
  }
}

function stopSceneStatusPolling() {
  if (state.sceneStatusTimer) {
    clearInterval(state.sceneStatusTimer);
    state.sceneStatusTimer = null;
  }
}

function startSceneStatusPolling() {
  stopSceneStatusPolling();
  if (!state.sceneId) return;
  const poll = async () => {
    try {
      const response = await fetch(API + "/api/scenes/" + encodeURIComponent(state.sceneId));
      if (!response.ok) return;
      const data = await response.json();
      state.sceneRecord = data;
      renderSceneRecord(data);
      if (data.status === "READY" || data.status === "FAILED" || data.status === "WAITING_FOR_TRAINER") {
        stopSceneStatusPolling();
      }
    } catch (error) {
      // The build keeps running on the backend; retry on the next interval.
    }
  };
  poll();
  state.sceneStatusTimer = setInterval(poll, 2500);
}

function startSceneBuildPreview(waitingForWorker = true) {
  stopSceneBuildPreview();
  const host = document.getElementById("scene-viewer");
  if (!host) return;
  const empty = host.querySelector(".scene-empty");
  let build = host.querySelector("#scene-build");
  // Older open tabs may still have the pre-preview DOM. Recreate the mount
  // point so a completed upload can switch to the build state without a
  // second navigation.
  if (!build) {
    build = document.createElement("div");
    build.id = "scene-build";
    build.className = "scene-build hidden";
    build.setAttribute("aria-live", "polite");
    host.appendChild(build);
  }
  if (empty) empty.classList.add("hidden");
  const tones = ["#62b5ff", "#a0d7ff", "#478fe1", "#d1ebff"];
  const points = Array.from({ length: 110 }, (_, index) => {
    const angle = index * 2.39996;
    const radius = 8 + (index % 11) * 3.7;
    const left = 50 + Math.cos(angle) * radius;
    const top = 47 + Math.sin(angle) * radius * .7;
    const size = 3 + (index % 4) * 1.2;
    const driftX = ((index % 7) - 3) * 3;
    const driftY = -8 - (index % 6) * 3;
    return '<span class="scene-splat" style="left:' + left.toFixed(2) + '%;top:' + top.toFixed(2) + '%;--size:' + size.toFixed(1) + 'px;--delay:-' + ((index % 18) / 6).toFixed(2) + 's;--drift-x:' + driftX + 'px;--drift-y:' + driftY + 'px;--tone:' + tones[index % tones.length] + '"></span>';
  }).join("");
  build.classList.remove("hidden");
  build.innerHTML = '<div class="scene-splat-field">' + points + '</div><div class="scene-build-halo"></div><div class="scene-build-copy"><span class="scene-build-kicker">REALITY CAPTURE</span><b id="scene-build-title">正在整理采集素材</b><small id="scene-build-detail">准备真实场景重建…</small><div class="scene-build-progress"><i id="scene-build-progress-bar"></i></div></div>';
  const stages = waitingForWorker
    ? [
      [18, "正在整理采集素材", "分析照片和视频…"],
      [36, "正在寻找相机轨迹", "准备空间重建…"],
      [52, "等待真实训练服务", "素材已经保存，连接训练机后会继续"],
    ]
    : [
      [18, "正在整理采集素材", "分析照片和视频…"],
      [48, "正在重建真实场景", "训练空间、材质和光影…"],
      [78, "正在生成可漫游场景", "马上可以进入浏览…"],
    ];
  let stageIndex = 0;
  const update = () => {
    const stage = stages[Math.min(stageIndex, stages.length - 1)];
    const title = document.getElementById("scene-build-title");
    const detail = document.getElementById("scene-build-detail");
    const bar = document.getElementById("scene-build-progress-bar");
    if (title) title.textContent = stage[1];
    if (detail) detail.textContent = stage[2];
    if (bar) bar.style.width = stage[0] + "%";
    stageIndex = Math.min(stageIndex + 1, stages.length - 1);
  };
  update();
  setSceneStatus(waitingForWorker ? "素材已保存 · 等待训练服务" : "正在重建真实场景…");
  state.sceneBuildTimer = setInterval(update, waitingForWorker ? 2600 : 2200);
}

function openSceneMode() {
  const panel = document.getElementById("scene-mode");
  if (!panel) return;
  document.getElementById("step-3d")?.classList.remove("active");
  panel.classList.add("open");
  panel.setAttribute("aria-hidden", "false");
  document.body.classList.add("scene-mode-active");
  setStatus("真实场景模式");
  updateSceneCaptureSelection();
  fetch(API + "/api/scenes/config").then(response => response.ok ? response.json() : null).then(config => {
    state.sceneTrainerConfigured = Boolean(config && config.trainerConfigured);
    if (state.sceneRecord) {
      renderSceneRecord(state.sceneRecord);
      if (state.sceneRecord.status === "CAPTURE_READY") {
        if (state.sceneTrainerConfigured === true) submitSceneToCloud(true);
        else if (!state.sceneRecord.result?.viewerUrl) startSceneBuildPreview(true);
      }
      if (state.sceneRecord.status === "CLOUD_QUEUED") {
        startSceneBuildPreview(false);
        startSceneStatusPolling();
      }
    }
  }).catch(() => { state.sceneTrainerConfigured = false; });
}

function closeSceneMode() {
  const panel = document.getElementById("scene-mode");
  panel?.classList.remove("open");
  panel?.setAttribute("aria-hidden", "true");
  document.body.classList.remove("scene-mode-active");
  document.getElementById("step-3d")?.classList.add("active");
  setStatus("3D 已加载，可以拖动旋转");
}

function uploadSceneCaptures(form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", API + "/api/scenes");
    xhr.timeout = 10 * 60 * 1000;
    xhr.upload.onprogress = event => {
      if (event.lengthComputable && onProgress) onProgress(Math.round(event.loaded / event.total * 100));
    };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText || "{}"); } catch (error) { /* handled below */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(data.detail || ("上传失败（" + (xhr.status || "网络错误") + "）")));
    };
    xhr.onerror = () => reject(new Error("上传失败，请检查本地服务是否还在运行"));
    xhr.ontimeout = () => reject(new Error("上传超时，请换用更短的视频或分批上传照片"));
    xhr.send(form);
  });
}

async function startSceneExperience() {
  const input = document.getElementById("scene-captures");
  const files = Array.from(input?.files || []);
  if (!files.length) { alert("请先选择环绕照片或视频"); return; }
  if (files.some(file => file.size > 80 * 1024 * 1024)) {
    setSceneStatus("单个文件不能超过 80 MB，请压缩视频后再试", true);
    return;
  }
  const button = document.getElementById("btn-scene-start");
  state.sceneUploading = true;
  if (button) { button.disabled = true; button.textContent = "上传 0%"; }
  const form = new FormData();
  form.append("title", document.getElementById("scene-title")?.value || "我的真实场景");
  files.forEach(file => form.append("captures", file, file.name));
  try {
    const data = await uploadSceneCaptures(form, percent => {
      if (button) button.textContent = "上传 " + percent + "%";
      setSceneStatus(percent < 100 ? "正在上传素材 " + percent + "%" : "素材已上传，正在整理…");
    });
    state.sceneId = data.sceneId;
    state.sceneRecord = data;
    renderSceneRecord(data);
    startSceneBuildPreview(state.sceneTrainerConfigured !== true);
    setStatus("采集已保存 · " + (data.quality?.message || "等待训练"));
    if (state.sceneTrainerConfigured === true) submitSceneToCloud(true);
  } catch (error) {
    console.error(error);
    setSceneStatus(error.message, true);
    setStatus("场景任务创建失败");
  } finally {
    state.sceneUploading = false;
    updateSceneCaptureSelection();
  }
}

function updateSceneCaptureSelection() {
  const input = document.getElementById("scene-captures");
  const files = Array.from(input?.files || []);
  const list = document.getElementById("scene-file-list");
  const start = document.getElementById("btn-scene-start");
  if (list) {
    list.innerHTML = files.length
      ? files.slice(0, 6).map(file => "<span>" + escapeHtml(file.name) + "</span>").join("") +
        (files.length > 6 ? "<small>还有 " + (files.length - 6) + " 个文件</small>" : "")
      : "还没有选择采集素材";
  }
  const saved = Boolean(state.sceneId && state.sceneRecord);
  if (start) {
    start.disabled = files.length === 0 || state.sceneUploading || saved;
    start.textContent = state.sceneUploading ? "上传中…" : saved ? "素材已保存" : "上传素材";
  }
  const quality = document.getElementById("scene-quality");
  if (quality) {
    const images = files.filter(file => file.type.startsWith("image/")).length;
    const videos = files.filter(file => file.type.startsWith("video/")).length;
    quality.textContent = images
      ? "已选择 " + images + " 张照片" + (videos ? " + " + videos + " 段视频" : "") + " · 建议至少 20 张"
      : videos ? "已选择 " + videos + " 段视频 · 云端会自动抽帧" : "上传后会检查数量和类型";
    quality.classList.toggle("ready", images >= 20 || videos > 0);
  }
}

async function submitSceneToCloud(auto = false) {
  if (!state.sceneId) return;
  const button = document.getElementById("btn-scene-submit");
  if (button) { button.disabled = true; button.textContent = auto ? "准备重建…" : "提交中…"; }
  if (auto) startSceneBuildPreview(false);
  try {
    const response = await fetch(API + "/api/scenes/" + encodeURIComponent(state.sceneId) + "/submit", { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "云训练器暂不可用");
    state.sceneRecord = data;
    renderSceneRecord(data);
    if (data.status === "CLOUD_QUEUED") {
      startSceneBuildPreview(false);
      startSceneStatusPolling();
    }
  } catch (error) {
    setSceneStatus(auto ? "素材已保存，等待训练机连接" : error.message, !auto);
  } finally {
    if (button) { button.disabled = !state.sceneId; button.textContent = "开始重建"; }
  }
}

async function importSceneAsset(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!state.sceneId) {
    setSceneStatus("请先创建一个场景任务，再导入训练成果", true);
    event.target.value = "";
    return;
  }
  const form = new FormData();
  form.append("asset", file, file.name);
  setSceneStatus("正在导入真实场景成果…");
  try {
    const response = await fetch(API + "/api/scenes/" + encodeURIComponent(state.sceneId) + "/asset", { method: "POST", body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "场景成果导入失败");
    state.sceneRecord = data;
    renderSceneRecord(data);
  } catch (error) {
    setSceneStatus(error.message, true);
  } finally {
    event.target.value = "";
  }
}

function setSceneStatus(message, error = false) {
  const node = document.getElementById("scene-status");
  if (!node) return;
  node.textContent = message || "";
  node.classList.toggle("error", error);
}

function renderSceneRecord(data) {
  const quality = document.getElementById("scene-quality");
  const submit = document.getElementById("btn-scene-submit");
  const manifest = document.getElementById("scene-manifest-link");
  const status = String(data.status || "");
  if (quality && data.quality) quality.textContent = data.quality.message;
  if (submit) {
    const canSubmit = status === "CAPTURE_READY" && state.sceneTrainerConfigured !== false;
    submit.disabled = !canSubmit;
    submit.classList.toggle("hidden", !canSubmit);
  }
  if (manifest) {
    manifest.href = data.captureManifestUrl || "#";
    manifest.classList.toggle("hidden", !data.captureManifestUrl);
  }
  const pipeline = document.getElementById("scene-pipeline");
  if (pipeline) {
    const spans = pipeline.querySelectorAll("span");
    spans.forEach((span, index) => span.classList.toggle("active", index === 0 || (index === 1 && status === "CLOUD_QUEUED") || (index === 2 && status === "READY")));
  }
  setSceneStatus(
    status === "CAPTURE_READY" && state.sceneTrainerConfigured === false
      ? "素材已保存，可下载清单或导入已有成果"
      : (data.message || status)
  );
  if (status === "FAILED" || status === "WAITING_FOR_TRAINER") {
    stopSceneBuildPreview();
  }
  if (data.result?.viewerUrl) {
    stopSceneStatusPolling();
    stopSceneBuildPreview();
    const host = document.getElementById("scene-viewer");
    if (host) {
      host.innerHTML = '<iframe title="真实场景查看器" src="' + escapeHtml(data.result.viewerUrl) + '&webgl&noui" allow="fullscreen; xr-spatial-tracking" allowfullscreen></iframe>';
    }
    setStatus("真实场景已生成，可以自由漫游");
  }
}

function buildExplodeParts(root) {
  _explodeParts = [];
  const modelCenter = new THREE.Box3().setFromObject(root).getCenter(new THREE.Vector3());
  const meshes = [];
  root.traverse(node => { if (node.isMesh) meshes.push(node); });
  meshes.forEach((node, index) => {
    const center = new THREE.Box3().setFromObject(node).getCenter(new THREE.Vector3());
    let direction = center.sub(modelCenter);
    if (direction.lengthSq() < 0.001) direction.set(index % 2 ? 1 : -1, index % 3 ? 0.35 : -0.25, index % 2 ? -0.3 : 0.4);
    direction.normalize();
    const parent = node.parent || root;
    const parentRotation = parent.getWorldQuaternion(new THREE.Quaternion()).invert();
    const parentScale = parent.getWorldScale(new THREE.Vector3());
    const offset = direction.multiplyScalar(30).applyQuaternion(parentRotation);
    offset.divide(parentScale);
    _explodeParts.push({ node, basePosition: node.position.clone(), offset });
  });
}

function applyExplosionFactor(factor) {
  _explodeParts.forEach(part => part.node.position.copy(part.basePosition).addScaledVector(part.offset, factor));
}

function updateExplodeStatus() {
  const status = document.getElementById("explode-status");
  const range = document.getElementById("explode-range");
  if (!status) return;
  if (_explodeParts.length <= 1) {
    status.textContent = "当前模型是单一网格，暂不能按零件拆开；可使用“半透明”查看外壳。";
    if (range) range.disabled = true;
  } else {
    status.textContent = `已识别 ${_explodeParts.length} 个可拆分零件，可以拖动拆解距离。`;
    if (range) range.disabled = false;
  }
}

function setExplosionFactor(value) {
  if (_explodeParts.length <= 1) return;
  _explodeTarget = Math.max(0, Math.min(1, value));
  const button = document.getElementById("btn-explode");
  if (button) {
    button.classList.toggle("active", _explodeTarget > 0);
    button.textContent = _explodeTarget > 0 ? "收起模型" : "拆开看";
  }
}

function toggleExplodedView() {
  if (_explodeParts.length <= 1) {
    updateExplodeStatus();
    return;
  }
  setExplosionFactor(_explodeTarget > 0 ? 0 : 1);
}

function toggleXrayView() {
  if (!_threeObj) return;
  state.xray = !state.xray;
  _threeObj.traverse(node => {
    if (!node.isMesh || !node.material) return;
    const materials = Array.isArray(node.material) ? node.material : [node.material];
    materials.forEach(material => {
      if (state.xray) {
        material.userData = material.userData || {};
        if (material.userData.originalOpacity == null) material.userData.originalOpacity = material.opacity;
        material.transparent = true;
        material.opacity = 0.34;
        material.depthWrite = false;
      } else {
        material.opacity = material.userData?.originalOpacity ?? 1;
        material.transparent = material.opacity < 1;
        material.depthWrite = true;
      }
      material.needsUpdate = true;
    });
  });
  const button = document.getElementById("btn-xray");
  if (button) button.classList.toggle("active", state.xray);
  const status = document.getElementById("explode-status");
  if (status) status.textContent = state.xray ? "已开启半透明查看；如果模型有内部零件，现在可以看到它们。" : "已恢复实体材质。";
}

function resetCamera() {
  if (!_threeCamera || !_threeCtrl || !_cameraHome) return;
  _threeCamera.position.copy(_cameraHome.position);
  _threeCtrl.target.copy(_cameraHome.target);
  _threeCtrl.update();
  setStatus("视角已重置");
}

function primitiveColor(hex) { return new THREE.Color(hex || "#ff719d"); }

function primitiveGeometry(kind) {
  if (kind === "cube") return new THREE.BoxGeometry(22, 22, 22);
  if (kind === "cone") return new THREE.ConeGeometry(14, 28, 32);
  if (kind === "cylinder") return new THREE.CylinderGeometry(12, 12, 24, 32);
  if (kind === "torus") return new THREE.TorusGeometry(11, 4, 16, 40);
  if (kind === "crystal") return new THREE.OctahedronGeometry(17, 1);
  if (kind === "capsule") return THREE.CapsuleGeometry ? new THREE.CapsuleGeometry(9, 14, 8, 24) : new THREE.CylinderGeometry(9, 9, 28, 24);
  if (kind === "heart") {
    const shape = new THREE.Shape();
    shape.moveTo(0, -8);
    shape.bezierCurveTo(-18, -20, -21, 3, 0, 17);
    shape.bezierCurveTo(21, 3, 18, -20, 0, -8);
    const geometry = new THREE.ExtrudeGeometry(shape, { depth: 7, bevelEnabled: true, bevelSegments: 3, bevelSize: 1.2, bevelThickness: 1.2 });
    geometry.center();
    return geometry;
  }
  return new THREE.SphereGeometry(14, 32, 20);
}

function addPrimitive(kind, descriptor = {}, recordUndo = true) {
  if (!_editorGroup) return;
  if (recordUndo) state.undoStack.push(capturePrimitiveState());
  const geometry = primitiveGeometry(kind);
  const material = new THREE.MeshStandardMaterial({
    color: primitiveColor(descriptor.color), roughness: .72, metalness: .03,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.userData = { editable: true, kind, color: descriptor.color || "#ff719d" };
  mesh.position.set(Number(descriptor.x ?? (Math.random() * 36 - 18)), Number(descriptor.y ?? (["cone", "cylinder", "capsule"].includes(kind) ? 14 : 11)), Number(descriptor.z ?? (Math.random() * 36 - 18)));
  mesh.rotation.set(Number(descriptor.rx || 0), Number(descriptor.ry || 0), Number(descriptor.rz || 0));
  mesh.scale.setScalar(Number(descriptor.scale || 1));
  _editorGroup.add(mesh);
  _editableNodes.push(mesh);
  selectEditable(mesh);
  const names = { sphere: "圆球", cube: "方块", cone: "圆锥", cylinder: "圆柱", torus: "圆环", crystal: "水晶", capsule: "胶囊", heart: "爱心" };
  setStatus(`已添加${names[kind] || "卡通素材"}`);
  if (recordUndo) {
    state.geometryDirty = true;
    scheduleProjectSave();
  }
  return mesh;
}

function handleCanvasPointer(event) {
  if (!_raycaster || !_threeCamera || !_threeCanvas) return;
  const rect = _threeCanvas.getBoundingClientRect();
  _pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  _pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  _raycaster.setFromCamera(_pointer, _threeCamera);
  const hits = _raycaster.intersectObjects(_editableNodes, true);
  if (!hits.length) { selectEditable(null); return; }
  let node = hits[0].object;
  while (node.parent && !node.userData.editable) node = node.parent;
  selectEditable(node);
}

function selectEditable(node) {
  state.selectedObject = node || null;
  if (_selectionHelper && _threeScene) { _threeScene.remove(_selectionHelper); _selectionHelper = null; }
  if (node && _threeScene) {
    _selectionHelper = new THREE.BoxHelper(node, 0xff6b9d);
    _threeScene.add(_selectionHelper);
  }
  updateInspector();
}

function updateInspector() {
  const empty = document.querySelector(".empty-inspector");
  const controls = document.getElementById("inspector-controls");
  const obj = state.selectedObject;
  if (!empty || !controls) return;
  const hasObject = Boolean(obj && obj.userData && obj.userData.kind !== "model");
  empty.classList.toggle("hidden", hasObject);
  controls.classList.toggle("hidden", !hasObject);
  if (!hasObject) return;
  document.getElementById("edit-x").value = Math.round(obj.position.x);
  document.getElementById("edit-z").value = Math.round(obj.position.z);
  document.getElementById("edit-scale").value = obj.scale.x.toFixed(2);
  document.querySelectorAll(".swatch").forEach(sw => sw.classList.toggle("active", sw.dataset.color.toLowerCase() === String(obj.userData.color || "").toLowerCase()));
}

function syncInspectorToObject() {
  const obj = state.selectedObject;
  if (!obj || obj.userData.kind === "model") return;
  if (!obj.userData._editing) { state.undoStack.push(capturePrimitiveState()); obj.userData._editing = true; }
  obj.position.x = Number(document.getElementById("edit-x").value);
  obj.position.z = Number(document.getElementById("edit-z").value);
  obj.scale.setScalar(Number(document.getElementById("edit-scale").value));
  state.geometryDirty = true;
  document.getElementById("save-state").textContent = "有未保存修改";
  scheduleProjectSave();
}

function endInspectorEdit() {
  if (state.selectedObject?.userData) state.selectedObject.userData._editing = false;
  scheduleProjectSave();
}

function setSelectedColor(hex) {
  const obj = state.selectedObject;
  if (!obj || obj.userData.kind === "model") return;
  state.undoStack.push(capturePrimitiveState());
  obj.userData.color = hex;
  obj.material.color.set(hex);
  state.geometryDirty = true;
  document.querySelectorAll(".swatch").forEach(sw => sw.classList.toggle("active", sw.dataset.color === hex));
  document.getElementById("save-state").textContent = "有未保存修改";
  scheduleProjectSave();
}

function duplicateSelected() {
  const obj = state.selectedObject;
  if (!obj || obj.userData.kind === "model") return;
  const descriptor = describePrimitive(obj);
  descriptor.x += 10; descriptor.z += 10;
  addPrimitive(descriptor.kind, descriptor, true);
}

function deleteSelected() {
  const obj = state.selectedObject;
  if (!obj || obj.userData.kind === "model") return;
  state.undoStack.push(capturePrimitiveState());
  _editorGroup.remove(obj);
  state.geometryDirty = true;
  _editableNodes = _editableNodes.filter(item => item !== obj);
  obj.geometry.dispose(); obj.material.dispose();
  selectEditable(null);
  document.getElementById("save-state").textContent = "有未保存修改";
  scheduleProjectSave();
}

function describePrimitive(obj) {
  return { kind: obj.userData.kind, color: obj.userData.color, x: obj.position.x, y: obj.position.y, z: obj.position.z, rx: obj.rotation.x, ry: obj.rotation.y, rz: obj.rotation.z, scale: obj.scale.x };
}

function capturePrimitiveState() {
  return _editableNodes.filter(obj => obj.userData.kind && obj.userData.kind !== "model").map(describePrimitive);
}

function restorePrimitiveState(snapshot) {
  if (!_editorGroup) return;
  _editableNodes.filter(obj => obj.userData.kind && obj.userData.kind !== "model").forEach(obj => { _editorGroup.remove(obj); obj.geometry.dispose(); obj.material.dispose(); });
  _editableNodes = _editableNodes.filter(obj => obj.userData.kind === "model");
  (snapshot || []).forEach(item => addPrimitive(item.kind, item, false));
  selectEditable(null);
}

function undoLastAction() {
  const snapshot = state.undoStack.pop();
  if (!snapshot) return;
  restorePrimitiveState(snapshot);
  state.geometryDirty = true;
  document.getElementById("save-state").textContent = "已撤销，未保存";
  scheduleProjectSave();
}

function projectPayload() {
  const active = state.modelVersions.find(version => version.id === state.activeVersionId);
  if (active && _editorGroup) active.primitives = capturePrimitiveState();
  const workbenchTitle = document.getElementById("workbench-project-title");
  const name = (workbenchTitle && workbenchTitle.value.trim())
    || document.getElementById("project-name").value.trim()
    || "我的卡通小世界";
  state.projectName = name;
  return {
    ...(state.projectId ? { id: state.projectId } : {}),
    name,
    sid: state.sid,
    meshUrl: state.meshUrl,
    prompt: state.currentPrompt,
    messages: state.messages,
    previews: state.previews.map((preview, index) => ({
      path: preview.path,
      caption: preview.caption || `图 ${index + 1}`,
      sub_prompt: preview.sub_prompt || "",
      index,
    })).filter(preview => preview.path),
    versions: state.modelVersions,
    activeVersionId: state.activeVersionId,
    canvas: { elements: state.canvasElements, viewport: state.canvasViewport },
    editor: { primitives: capturePrimitiveState() },
    selection: state.selectedIndex == null ? null : {
      session_id: state.previewSessionId || state.sid,
      image_index: state.selectedIndex,
      version_id: state.activeVersionId,
    },
  };
}

function scheduleProjectSave() {
  const stateLabel = document.getElementById("save-state");
  if (stateLabel) stateLabel.textContent = "有未保存修改";
  if (state.saveTimer) clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => saveProject({ automatic: true }), 700);
}

async function saveProject({ automatic = false } = {}) {
  if (state.saving) {
    scheduleProjectSave();
    return;
  }
  state.saving = true;
  const stateLabel = document.getElementById("save-state");
  const savedNote = document.getElementById("saved-note");
  try {
    const body = projectPayload();
    const response = state.projectId
      ? await fetch(`${API}/api/projects/${encodeURIComponent(state.projectId)}`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      })
      : await fetch(`${API}/api/projects`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const saved = await response.json();
    state.projectId = saved.id;
    if (stateLabel) stateLabel.textContent = "已保存";
    if (savedNote) savedNote.textContent = saved.missingReferences?.length
      ? `已保存 · ${saved.missingReferences.length} 个素材文件缺失，引用已保留`
      : "已保存到本机，可随时回来继续编辑";
    if (!automatic) renderSavedProjects();
  } catch (error) {
    if (stateLabel) stateLabel.textContent = "保存失败，可重试";
    if (savedNote) savedNote.textContent = `本机保存失败：${error.message}`;
  } finally {
    state.saving = false;
  }
}

async function readProjects() {
  try {
    const response = await fetch(`${API}/api/projects`);
    if (!response.ok) throw new Error("project list unavailable");
    return (await response.json()).projects || [];
  } catch {
    try { return JSON.parse(localStorage.getItem("cartoon-print-projects") || "[]"); } catch { return []; }
  }
}

async function migrateLegacyProjects() {
  const marker = "cartoon-projects-migrated-v1";
  if (localStorage.getItem(marker)) return;
  let legacy;
  try { legacy = JSON.parse(localStorage.getItem("cartoon-print-projects") || "[]"); } catch { return; }
  if (!Array.isArray(legacy) || !legacy.length) {
    localStorage.setItem(marker, "1");
    return;
  }
  try {
    const response = await fetch(`${API}/api/projects`);
    if (!response.ok) return;
    const existing = (await response.json()).projects || [];
    for (const item of legacy) {
      if (!item || existing.some(project => project.legacyId === item.id)) continue;
      const versions = item.sid && item.meshUrl ? [{
        id: item.sid, sid: item.sid, meshUrl: item.meshUrl,
        engine: "legacy", prompt: item.prompt || "", createdAt: item.updatedAt || Date.now(),
        primitives: Array.isArray(item.primitives) ? item.primitives : [],
      }] : [];
      const imported = await fetch(`${API}/api/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: item.name || "我的卡通小世界",
          legacyId: item.id || null,
          sid: item.sid || null,
          meshUrl: item.meshUrl || null,
          prompt: item.prompt || "",
          messages: [],
          previews: [],
          versions,
          activeVersionId: versions[0]?.id || null,
          canvas: { elements: [] },
          editor: { primitives: item.primitives || [] },
          selection: null,
        }),
      });
      if (!imported.ok) return;
    }
    localStorage.setItem(marker, "1");
  } catch {
    // Keep the original localStorage data and retry migration next launch.
  }
}

function openLibrary() {
  renderSavedProjects();
  document.getElementById("library-drawer").classList.add("open");
  document.getElementById("library-drawer").setAttribute("aria-hidden", "false");
  document.getElementById("drawer-backdrop").classList.remove("hidden");
}
function closeLibrary() {
  document.getElementById("library-drawer").classList.remove("open");
  document.getElementById("library-drawer").setAttribute("aria-hidden", "true");
  document.getElementById("drawer-backdrop").classList.add("hidden");
}

async function renderSavedProjects() {
  const host = document.getElementById("saved-projects");
  if (!host) return;
  host.textContent = "正在读取本机作品…";
  const projects = await readProjects();
  if (!projects.length) {
    host.innerHTML = '<div class="library-empty">还没有保存的作品。先生成一个 3D 模型，再添加几个卡通素材试试吧。</div>';
    return;
  }
  host.innerHTML = projects.map(project => `<div class="saved-project"><div><strong>${escapeHtml(project.name || "我的创作")}</strong><small>${project.updatedAt ? new Date(project.updatedAt * 1000).toLocaleString() : ""} · ${project.versionCount || project.versions?.length || 0} 个模型版本</small></div><button type="button" data-load-project="${escapeHtml(project.id)}">继续编辑</button></div>`).join("");
  host.querySelectorAll("[data-load-project]").forEach(btn => btn.addEventListener("click", () => restoreProject(btn.dataset.loadProject)));
}

async function restoreProject(id) {
  try {
    const response = await fetch(`${API}/api/projects/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error("找不到这个本机作品");
    const project = await response.json();
    closeLibrary();
    state.projectId = project.id;
    state.sid = project.sid || null;
    state.currentPrompt = project.prompt || "";
    state.messages = project.messages || [];
    state.previews = (project.previews || []).map(preview => ({
      ...preview, session_id: project.selection?.session_id || project.sid,
    }));
    state.previewSessionId = project.selection?.session_id || project.sid || null;
    state.modelVersions = project.versions || [];
    state.activeVersionId = project.activeVersionId || project.selection?.version_id || state.modelVersions.at(-1)?.id || null;
    state.canvasElements = project.canvas?.elements || [];
    state.canvasViewport = project.canvas?.viewport || { x: 0, y: 0, zoom: 1 };
    state.selectedIndex = Number.isInteger(project.selection?.image_index) ? project.selection.image_index : null;
    state.meshUrl = project.meshUrl || null;
    const active = state.modelVersions.find(version => version.id === state.activeVersionId);
    if (active) {
      state.sid = active.sid || state.sid;
      state.meshUrl = active.meshUrl || state.meshUrl;
    }
    document.getElementById("project-name").value = project.name || "我的卡通小世界";
    state.projectName = project.name || "我的卡通小世界";
    const workbenchTitle = document.getElementById("workbench-project-title");
    if (workbenchTitle) workbenchTitle.value = state.projectName;
    document.getElementById("prompt").value = state.currentPrompt;
    document.getElementById("save-state").textContent = project.missingReferences?.length ? "部分素材缺失" : "已载入";
    document.getElementById("saved-note").textContent = project.missingReferences?.length
      ? `${project.missingReferences.length} 个素材文件暂不可用；项目记录已保留`
      : "本机项目已恢复";
    if (state.meshUrl) {
      show("#step-3d");
      initThree(state.meshUrl, active?.primitives || project.editor?.primitives || []);
    } else if (state.previews.length) {
      renderPreviews();
      show("#step-pick");
    }
    renderModelVersions();
    workbenchInternals.renderCanvas();
    workbenchInternals.renderConversation();
    scheduleProjectSave();
  } catch (error) {
    alert(`恢复作品失败：${error.message}`);
  }
}

function renderModelVersions() {
  const host = document.getElementById("model-versions");
  if (!host) return;
  host.replaceChildren();
  if (!state.modelVersions.length) return;
  const label = document.createElement("span");
  label.className = "version-label";
  label.textContent = "模型版本";
  host.appendChild(label);
  state.modelVersions.forEach((version, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "version-button";
    button.classList.toggle("active", version.id === state.activeVersionId);
    button.textContent = `V${index + 1} · ${version.engine || "模型"}`;
    button.title = version.prompt || `模型版本 ${index + 1}`;
    button.addEventListener("click", () => switchModelVersion(version.id));
    host.appendChild(button);
  });
}

function switchModelVersion(versionId) {
  const next = state.modelVersions.find(version => version.id === versionId);
  if (!next || !next.meshUrl) return;
  const current = state.modelVersions.find(version => version.id === state.activeVersionId);
  if (current && _editorGroup) current.primitives = capturePrimitiveState();
  state.activeVersionId = next.id;
  state.sid = next.sid;
  state.meshUrl = next.meshUrl;
  state.previewSessionId = next.sid;
  state.selectedIndex = next.imageIndex ?? state.selectedIndex;
  initThree(next.meshUrl, next.primitives || []);
  renderModelVersions();
  scheduleProjectSave();
}
// initial health check
fetch(API + "/api/scenes/config").then(r => r.json()).then(config => {
  state.sceneTrainerConfigured = Boolean(config.trainerConfigured);
}).catch(() => { state.sceneTrainerConfigured = false; });

// Startup state: which local services are usable right now, and what the user
// can still do when a cloud provider or an API key is missing.
function renderStartupStatus(messages, tone) {
  const host = document.getElementById("workbench-startup-status");
  if (!host) return;
  host.replaceChildren();
  if (!messages.length) {
    host.hidden = true;
    host.textContent = "";
    return;
  }
  host.hidden = false;
  host.dataset.tone = tone || "warn";
  host.textContent = messages.join("　");
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "mini-btn";
  retry.textContent = "重新检测";
  retry.addEventListener("click", () => refreshStartupStatus());
  host.appendChild(retry);
}

function describeHealth(j) {
  const notes = [];
  const hasImageKeys = (j.minimax_image_keys || 0) + (j.jojo_alive_keys || 0) > 0;
  if (!hasImageKeys) {
    notes.push("未检测到可用的生图 API 密钥：云端预览不可用，本机卡通浮雕与卡通 3D 仍可使用。");
  }
  if (!(j.llm_keys || 0)) {
    notes.push("未检测到提示词润色密钥：润色会退回本机规则建议。");
  }
  if (j.tripo3d_key_loaded && j.tripo3d_ok && j.tripo3d_balance < 30) {
    notes.push("Tripo 额度不足");
  }
  if (!notes.length) {
    renderStartupStatus([], "ok");
  } else {
    renderStartupStatus(notes, "warn");
  }
}

async function refreshStartupStatus() {
  try {
    const response = await fetch(API + "/api/health");
    const j = await response.json();
    setStatus(j.ok ? "准备就绪" : "暂时离线");
    refreshBambuBanner();
    refreshEngineOptions();
    describeHealth(j);
    // The first health call only kicks off the provider probe; ask again
    // shortly afterwards so the notice settles on the real state.
    if (j.tripo3d_checking) {
      setTimeout(() => refreshStartupStatus(), 3000);
    }
  } catch (error) {
    setStatus("正在连接");
    renderStartupStatus([
      `后端没有响应（${error.message}）：请确认服务已启动，端口被占用时可换端口 scripts\\start_backend.ps1 -Port 8010。`,
    ], "error");
  }
}

refreshStartupStatus();


// ------------------------------------------------------------------
// 进度条 — 真正的"演化"显示
// ------------------------------------------------------------------
const PHASE_LABEL = {
  "previews":      "✦ 生成 2D 预览",
  "3d-hunyuan":    "◆ Hunyuan3D 重建中",
  "3d-triposr":    "◆ TripoSR 重建中",
  "print":         "▶ 发送到 Bambu Studio",
};

function setProgress(percent, message, phase, step) {
  const bar = document.getElementById("progress-bar-fill");
  const wrap = document.getElementById("progress-bar");
  const pct = document.getElementById("progress-pct");
  const txt = document.getElementById("progress-msg");
  const chip = document.getElementById("progress-phase");
  const loader = document.getElementById("loader-text");
  const stage = document.getElementById("build-stage");

  const p = Math.max(0, Math.min(100, Math.round(percent || 0)));
  if (bar) {
    bar.style.width = p + "%";
    bar.setAttribute("data-pct", p);
  }
  if (wrap) {
    wrap.classList.remove("is-done", "is-fail");
    if (step === "done")  wrap.classList.add("is-done");
    if (step === "fail")  wrap.classList.add("is-fail");
  }
  if (pct) pct.textContent = p + "%";
  if (stage) {
    stage.style.setProperty("--build-progress", `${Math.max(8, p)}%`);
    document.getElementById("build-step-shape")?.classList.toggle("active", p < 40);
    document.getElementById("build-step-detail")?.classList.toggle("active", p >= 40 && p < 72);
    document.getElementById("build-step-mesh")?.classList.toggle("active", p >= 72);
  }
  if (chip) {
    const label = PHASE_LABEL[phase] || (phase ? "▶ " + phase : null);
    if (label) chip.textContent = label;
  }
  if (txt && message) txt.textContent = message;

  // 让"加载中文案"和进度面板保持同步 — 告诉用户"现在卡在哪一步"
  if (loader && message && step && step !== "start") {
    loader.textContent = message.length > 36 ? message.slice(0, 36) + "…" : message;
  }

  // 重置 idle 计时
  _touchIdleTimer(p);
}

let _idleTimer = null;
function _touchIdleTimer(percent) {
  const wrap = document.getElementById("progress-bar");
  if (!wrap) return;
  wrap.classList.remove("is-idle");
  if (_idleTimer) clearTimeout(_idleTimer);
  // 长时间没新事件时,加 is-idle 让条纹加速脉动,告诉用户"还在等"
  _idleTimer = setTimeout(() => {
    if (percent < 100) wrap.classList.add("is-idle");
  }, 4500);
}

function stopProgressPolling() {
  if (_progressPollTimer) { clearInterval(_progressPollTimer); _progressPollTimer = null; }
  if (_idleTimer)        { clearTimeout(_idleTimer);         _idleTimer        = null; }
  const wrap = document.getElementById("progress-bar");
  if (wrap) wrap.classList.remove("is-idle");
}

async function startProgressPolling(sid) {
  if (_progressPollTimer) clearInterval(_progressPollTimer);
  _progressLastTs = 0;
  const poll = async () => {
    try {
      const r = await fetch(`${API}/api/progress/${sid}?since=${_progressLastTs}`);
      if (!r.ok) return;
      const j = await r.json();
      if (j.events && j.events.length) {
        _progressLastTs = j.events[j.events.length - 1].ts;
        for (const ev of j.events) {
          setProgress(ev.percent, ev.message, ev.phase, ev.step);
          feed(`[${ev.phase}] ${ev.message}`);
        }
        if (j.latest && (j.latest.step === "done" || j.latest.step === "fail")) {
          stopProgressPolling();
        }
      }
    } catch (e) { /* ignore */ }
  };
  await poll();
  _progressPollTimer = setInterval(poll, 1500);
}

// ------------------------------------------------------------------
// Wait for the background previews worker to finish, then fetch result.
// ------------------------------------------------------------------
async function waitForPreviews(sid) {
  // Poll progress until we see step=done
  let lastStep = null;
  for (let i = 0; i < 240; i++) {  // up to ~6 min
    await new Promise(r => setTimeout(r, 1500));
    try {
      const r = await fetch(API + "/api/progress/" + sid + "?since=0");
      if (!r.ok) continue;
      const j = await r.json();
      const latest = j.latest;
      if (latest && latest.step === "done") {
        lastStep = "done";
        break;
      }
      if (latest && latest.step === "fail") {
        throw new Error(latest.message || "生成失败");
      }
    } catch (e) { /* keep polling */ }
  }
  if (lastStep !== "done") throw new Error("等待超时");
  // Fetch final result
  const r2 = await fetch(API + "/api/session/" + sid + "/result");
  if (!r2.ok) throw new Error("HTTP " + r2.status);
  state._lastPreviewsData = await r2.json();
}

// ------------------------------------------------------------------
// Workbench wiring
// ------------------------------------------------------------------
initWorkbench({
  state,
  generateModel,
  renderPreviews,
  saveProject,
  scheduleProjectSave,
  switchModelVersion,
  openLibrary,
  initThree,
  capturePrimitiveState,
  renderModelVersions,
  persistEditedModel,
  canPersistEditedModel,
});
