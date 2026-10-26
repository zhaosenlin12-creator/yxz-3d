/**
 * Creation workbench: chat on the left, infinite canvas in the middle,
 * properties and delivery on the right.
 *
 * All workbench state lives in the shared app state object that app.js
 * passes in, so the canvas, the conversation and the model versions are
 * saved together as one project document.
 */

const $ = (selector) => document.querySelector(selector);

const PREVIEW_WIDTH = 188;
const PREVIEW_HEIGHT = 176;
const NOTE_WIDTH = 220;
const NOTE_HEIGHT = 130;
const MIN_ZOOM = 0.2;
const MAX_ZOOM = 4;
const MAX_ELEMENTS = 400;

let app = null;
let dom = {};

const canvas = {
  selection: [],
  undoStack: [],
  redoStack: [],
  mode: "select",
  pointer: null,
  spaceDown: false,
};

const voice = {
  recognition: null,
  listening: false,
  baseText: "",
  startText: "",
  finalized: "",
  lastApplied: null,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function uid(prefix = "el") {
  const random = Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
  return `${prefix}_${random}`;
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function readError(response) {
  const body = await response.text().catch(() => "");
  if (!body) return `HTTP ${response.status}`;
  try {
    const parsed = JSON.parse(body);
    if (parsed && parsed.detail) return String(parsed.detail);
  } catch (error) {
    /* not JSON, fall through to the raw body */
  }
  return body.slice(0, 200);
}

function elements() {
  if (!app.state.canvasElements) app.state.canvasElements = [];
  return app.state.canvasElements;
}

function snapshotElements() {
  return JSON.stringify(elements());
}

function pushUndo() {
  canvas.undoStack.push(snapshotElements());
  if (canvas.undoStack.length > 80) canvas.undoStack.shift();
  canvas.redoStack.length = 0;
}

function undo() {
  if (!canvas.undoStack.length) return;
  canvas.redoStack.push(snapshotElements());
  app.state.canvasElements = JSON.parse(canvas.undoStack.pop());
  canvas.selection = canvas.selection.filter((id) => elementById(id));
  renderCanvas();
  app.scheduleProjectSave();
}

function redo() {
  if (!canvas.redoStack.length) return;
  canvas.undoStack.push(snapshotElements());
  app.state.canvasElements = JSON.parse(canvas.redoStack.pop());
  canvas.selection = canvas.selection.filter((id) => elementById(id));
  renderCanvas();
  app.scheduleProjectSave();
}

function nextZ() {
  return elements().reduce((highest, element) => Math.max(highest, Number(element.z) || 0), 0) + 1;
}

function selectedElements() {
  return elements().filter((element) => canvas.selection.includes(element.id));
}

function elementById(id) {
  return elements().find((element) => element.id === id) || null;
}

// ---------------------------------------------------------------------------
// Canvas geometry
// ---------------------------------------------------------------------------

function viewport() {
  if (!app.state.canvasViewport) app.state.canvasViewport = { x: 0, y: 0, zoom: 1 };
  return app.state.canvasViewport;
}

function viewportCenter() {
  const rect = dom.viewport.getBoundingClientRect();
  return { x: rect.width / 2, y: rect.height / 2 };
}

function screenToWorld(clientX, clientY) {
  const rect = dom.viewport.getBoundingClientRect();
  const center = viewportCenter();
  const view = viewport();
  return {
    x: (clientX - rect.left - center.x - view.x) / view.zoom,
    y: (clientY - rect.top - center.y - view.y) / view.zoom,
  };
}

function applyViewport() {
  const view = viewport();
  dom.world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`;
  dom.zoomLabel.textContent = `${Math.round(view.zoom * 100)}%`;
}

function setZoom(nextZoom, anchor) {
  const view = viewport();
  const target = clamp(nextZoom, MIN_ZOOM, MAX_ZOOM);
  if (Math.abs(target - view.zoom) < 0.0001) return;
  if (anchor) {
    const rect = dom.viewport.getBoundingClientRect();
    const center = viewportCenter();
    const worldX = (anchor.x - rect.left - center.x - view.x) / view.zoom;
    const worldY = (anchor.y - rect.top - center.y - view.y) / view.zoom;
    view.x = anchor.x - rect.left - center.x - worldX * target;
    view.y = anchor.y - rect.top - center.y - worldY * target;
  }
  view.zoom = target;
  applyViewport();
  app.scheduleProjectSave();
}

function zoomToFit() {
  const items = elements();
  const view = viewport();
  if (!items.length) {
    view.x = 0;
    view.y = 0;
    view.zoom = 1;
    applyViewport();
    return;
  }
  const bounds = boundsOf(items);
  const rect = dom.viewport.getBoundingClientRect();
  const padding = 48;
  const scale = Math.min(
    (rect.width - padding * 2) / Math.max(bounds.width, 1),
    (rect.height - padding * 2) / Math.max(bounds.height, 1),
  );
  view.zoom = clamp(scale, MIN_ZOOM, MAX_ZOOM);
  const center = viewportCenter();
  view.x = -bounds.x * view.zoom + center.x - (bounds.width * view.zoom) / 2;
  view.y = -bounds.y * view.zoom + center.y - (bounds.height * view.zoom) / 2;
  applyViewport();
  app.scheduleProjectSave();
}

function resetView() {
  const view = viewport();
  view.x = 0;
  view.y = 0;
  view.zoom = 1;
  applyViewport();
  app.scheduleProjectSave();
}

function boundsOf(items) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const item of items) {
    const width = Number(item.width) || 0;
    const height = Number(item.height) || 0;
    minX = Math.min(minX, Number(item.x) || 0);
    minY = Math.min(minY, Number(item.y) || 0);
    maxX = Math.max(maxX, (Number(item.x) || 0) + width);
    maxY = Math.max(maxY, (Number(item.y) || 0) + height);
  }
  if (!Number.isFinite(minX)) return { x: 0, y: 0, width: 0, height: 0 };
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

// ---------------------------------------------------------------------------
// Canvas rendering
// ---------------------------------------------------------------------------

function renderCanvas() {
  const items = elements();
  const seen = new Set();
  const nodes = new Map();
  for (const node of Array.from(dom.world.children)) {
    if (node.dataset && node.dataset.elementId) nodes.set(node.dataset.elementId, node);
  }

  const ordered = items.slice().sort((a, b) => (Number(a.z) || 0) - (Number(b.z) || 0));
  ordered.forEach((element) => {
    seen.add(element.id);
    let node = nodes.get(element.id);
    if (!node) {
      node = createNode(element);
      dom.world.appendChild(node);
    }
    updateNode(node, element);
  });
  for (const [id, node] of nodes) {
    if (!seen.has(id)) node.remove();
  }

  dom.empty.classList.toggle("hidden", items.length > 0);
  dom.itemCount.textContent = `${items.length} 项`;
  updateInspector();
  applyViewport();
}

function createNode(element) {
  const node = document.createElement("div");
  node.className = `canvas-node ${element.type}`;
  node.dataset.elementId = element.id;
  node.tabIndex = 0;
  node.setAttribute("role", "group");
  return node;
}

function updateNode(node, element) {
  node.style.left = `${Number(element.x) || 0}px`;
  node.style.top = `${Number(element.y) || 0}px`;
  node.style.zIndex = String(Math.round(Number(element.z) || 0));
  node.classList.toggle("selected", canvas.selection.includes(element.id));

  if (element.type === "stroke") {
    const width = Math.max(Number(element.width) || 1, 1);
    const height = Math.max(Number(element.height) || 1, 1);
    node.style.width = `${width}px`;
    node.style.height = `${height}px`;
    const svg = node.querySelector("svg") || document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");
    const path = svg.querySelector("path") || document.createElementNS("http://www.w3.org/2000/svg", "path");
    const points = Array.isArray(element.points) ? element.points : [];
    path.setAttribute("d", points.map((point, index) => (
      `${index === 0 ? "M" : "L"} ${(Number(point[0]) || 0).toFixed(2)} ${(Number(point[1]) || 0).toFixed(2)}`
    )).join(" "));
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", element.strokeColor || "#2676c9");
    path.setAttribute("stroke-width", String(Number(element.strokeWidth) || 4));
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    if (!path.parentNode) svg.appendChild(path);
    if (!svg.parentNode) node.appendChild(svg);
    node.setAttribute("aria-label", "自由笔迹标注");
    return;
  }

  if (element.type === "note") {
    if (!node.querySelector(".note-handle")) {
      const handle = document.createElement("div");
      handle.className = "note-handle";
      handle.setAttribute("role", "button");
      handle.setAttribute("tabindex", "0");
      handle.setAttribute("aria-label", "拖动便签");
      handle.textContent = "便签";
      node.appendChild(handle);
    }
    if (!node.querySelector("textarea")) {
      const area = document.createElement("textarea");
      area.rows = 4;
      area.maxLength = 20000;
      area.setAttribute("aria-label", "便签内容");
      area.addEventListener("input", () => {
        element.text = area.value;
        app.scheduleProjectSave();
      });
      area.addEventListener("pointerdown", (event) => event.stopPropagation());
      node.appendChild(area);
    }
    const area = node.querySelector("textarea");
    if (area && document.activeElement !== area && area.value !== (element.text || "")) {
      area.value = element.text || "";
    }
    node.style.width = `${Number(element.width) || NOTE_WIDTH}px`;
    node.style.height = `${Number(element.height) || NOTE_HEIGHT}px`;
    node.setAttribute("aria-label", "文本便签");
    return;
  }

  if (element.type === "model") {
    node.textContent = "";
    const title = document.createElement("strong");
    title.textContent = element.label || "3D 模型";
    const detail = document.createElement("span");
    detail.textContent = element.detail || "点击打开 3D 编辑器";
    node.appendChild(title);
    node.appendChild(detail);
    node.style.width = `${Number(element.width) || PREVIEW_WIDTH}px`;
    node.style.height = `${Number(element.height) || 120}px`;
    node.setAttribute("aria-label", `3D 模型 ${element.label || ""}`);
    return;
  }

  let picture = node.querySelector("img");
  if (!picture) {
    node.textContent = "";
    picture = document.createElement("img");
    picture.draggable = false;
    node.appendChild(picture);
    const caption = document.createElement("div");
    caption.className = "canvas-node-caption";
    node.appendChild(caption);
  }
  picture.src = element.path || "";
  picture.alt = element.caption || "画布图片";
  node.querySelector(".canvas-node-caption").textContent = element.caption || "";
  node.style.width = `${Number(element.width) || PREVIEW_WIDTH}px`;
  node.setAttribute("aria-label", element.caption || "画布图片");
}

// ---------------------------------------------------------------------------
// Canvas interaction
// ---------------------------------------------------------------------------

function setMode(mode) {
  canvas.mode = mode;
  const buttons = { select: dom.toolSelect, note: dom.toolNote, draw: dom.toolDraw };
  Object.entries(buttons).forEach(([name, button]) => {
    if (!button) return;
    const active = name === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  dom.viewport.dataset.mode = mode;
}

function isTypingTarget(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable;
}

function onPointerDown(event) {
  if (event.button === 1 || canvas.spaceDown) {
    canvas.pointer = {
      kind: "pan",
      startX: event.clientX,
      startY: event.clientY,
      originX: viewport().x,
      originY: viewport().y,
    };
    dom.viewport.setPointerCapture(event.pointerId);
    event.preventDefault();
    return;
  }
  if (event.button !== 0) return;
  const node = event.target.closest ? event.target.closest(".canvas-node") : null;
  const world = screenToWorld(event.clientX, event.clientY);

  if (canvas.mode === "draw") {
    canvas.pointer = {
      kind: "draw",
      points: [[world.x, world.y]],
      color: dom.strokeColor.value,
      width: Number(dom.strokeWidth.value),
    };
    dom.viewport.setPointerCapture(event.pointerId);
    event.preventDefault();
    return;
  }
  if (canvas.mode === "note") {
    pushUndo();
    const note = {
      id: uid("note"),
      type: "note",
      x: world.x - NOTE_WIDTH / 2,
      y: world.y - NOTE_HEIGHT / 2,
      width: NOTE_WIDTH,
      height: NOTE_HEIGHT,
      z: nextZ(),
      text: "",
    };
    elements().push(note);
    canvas.selection = [note.id];
    setMode("select");
    renderCanvas();
    app.scheduleProjectSave();
    const area = dom.world.querySelector(`[data-element-id="${note.id}"] textarea`);
    if (area) area.focus();
    return;
  }

  if (node) {
    const id = node.dataset.elementId;
    if (event.shiftKey) {
      canvas.selection = canvas.selection.includes(id)
        ? canvas.selection.filter((value) => value !== id)
        : [...canvas.selection, id];
    } else if (!canvas.selection.includes(id)) {
      canvas.selection = [id];
    }
    renderCanvas();
    const picked = selectedElements();
    if (!picked.length) return;
    pushUndo();
    canvas.pointer = {
      kind: "move",
      startX: event.clientX,
      startY: event.clientY,
      items: picked.map((element) => ({ id: element.id, x: Number(element.x) || 0, y: Number(element.y) || 0 })),
      moved: false,
    };
    dom.viewport.setPointerCapture(event.pointerId);
    event.preventDefault();
    return;
  }

  if (!event.shiftKey) canvas.selection = [];
  canvas.pointer = { kind: "marquee", startWorld: world, currentWorld: world };
  dom.viewport.setPointerCapture(event.pointerId);
  renderCanvas();
  event.preventDefault();
}

function onPointerMove(event) {
  const pointer = canvas.pointer;
  if (!pointer) return;
  const world = screenToWorld(event.clientX, event.clientY);
  if (pointer.kind === "pan") {
    const view = viewport();
    view.x = pointer.originX + (event.clientX - pointer.startX);
    view.y = pointer.originY + (event.clientY - pointer.startY);
    applyViewport();
    return;
  }
  if (pointer.kind === "move") {
    const dx = (event.clientX - pointer.startX) / viewport().zoom;
    const dy = (event.clientY - pointer.startY) / viewport().zoom;
    if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) pointer.moved = true;
    for (const entry of pointer.items) {
      const element = elementById(entry.id);
      if (!element) continue;
      element.x = entry.x + dx;
      element.y = entry.y + dy;
    }
    renderCanvas();
    return;
  }
  if (pointer.kind === "draw") {
    const last = pointer.points[pointer.points.length - 1];
    if (!last || Math.abs(last[0] - world.x) > 1.5 || Math.abs(last[1] - world.y) > 1.5) {
      pointer.points.push([world.x, world.y]);
    }
    return;
  }
  if (pointer.kind === "marquee") {
    pointer.currentWorld = world;
    updateMarquee(pointer);
  }
}

function onPointerUp(event) {
  const pointer = canvas.pointer;
  canvas.pointer = null;
  if (dom.viewport.hasPointerCapture && dom.viewport.hasPointerCapture(event.pointerId)) {
    dom.viewport.releasePointerCapture(event.pointerId);
  }
  if (!pointer) return;
  if (pointer.kind === "move") {
    if (!pointer.moved) canvas.undoStack.pop();
    app.scheduleProjectSave();
    return;
  }
  if (pointer.kind === "marquee") {
    if (dom.marquee) {
      dom.marquee.remove();
      dom.marquee = null;
    }
    const area = {
      x: Math.min(pointer.startWorld.x, pointer.currentWorld.x),
      y: Math.min(pointer.startWorld.y, pointer.currentWorld.y),
      width: Math.abs(pointer.currentWorld.x - pointer.startWorld.x),
      height: Math.abs(pointer.currentWorld.y - pointer.startWorld.y),
    };
    if (area.width > 3 || area.height > 3) {
      const hits = elements().filter((element) => {
        const bounds = boundsOf([element]);
        return bounds.x < area.x + area.width
          && bounds.x + bounds.width > area.x
          && bounds.y < area.y + area.height
          && bounds.y + bounds.height > area.y;
      }).map((element) => element.id);
      canvas.selection = Array.from(new Set([...canvas.selection, ...hits]));
    }
    renderCanvas();
    return;
  }
  if (pointer.kind === "draw") finishStroke(pointer);
}

function updateMarquee(pointer) {
  if (!dom.marquee) {
    dom.marquee = document.createElement("div");
    dom.marquee.className = "canvas-marquee";
    dom.world.appendChild(dom.marquee);
  }
  const x = Math.min(pointer.startWorld.x, pointer.currentWorld.x);
  const y = Math.min(pointer.startWorld.y, pointer.currentWorld.y);
  dom.marquee.style.left = `${x}px`;
  dom.marquee.style.top = `${y}px`;
  dom.marquee.style.width = `${Math.abs(pointer.currentWorld.x - pointer.startWorld.x)}px`;
  dom.marquee.style.height = `${Math.abs(pointer.currentWorld.y - pointer.startWorld.y)}px`;
}

function finishStroke(pointer) {
  const points = pointer.points;
  if (points.length < 2) return;
  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const maxX = Math.max(...xs);
  const maxY = Math.max(...ys);
  pushUndo();
  const stroke = {
    id: uid("stroke"),
    type: "stroke",
    x: minX,
    y: minY,
    width: Math.max(maxX - minX, 1),
    height: Math.max(maxY - minY, 1),
    z: nextZ(),
    strokeColor: pointer.color,
    strokeWidth: pointer.width,
    points: points.map((point) => [point[0] - minX, point[1] - minY]),
  };
  elements().push(stroke);
  canvas.selection = [stroke.id];
  renderCanvas();
  app.scheduleProjectSave();
}

function onWheel(event) {
  event.preventDefault();
  const factor = event.deltaY > 0 ? 0.92 : 1.08;
  setZoom(viewport().zoom * factor, { x: event.clientX, y: event.clientY });
}

function nudgeSelection(dx, dy) {
  const picked = selectedElements();
  if (!picked.length) return;
  pushUndo();
  for (const element of picked) {
    element.x = (Number(element.x) || 0) + dx;
    element.y = (Number(element.y) || 0) + dy;
  }
  renderCanvas();
  app.scheduleProjectSave();
}

function deleteSelection() {
  const picked = selectedElements();
  if (!picked.length) return;
  pushUndo();
  const ids = new Set(picked.map((element) => element.id));
  app.state.canvasElements = elements().filter((element) => !ids.has(element.id));
  canvas.selection = [];
  renderCanvas();
  app.scheduleProjectSave();
}

function bringToFront() {
  const picked = selectedElements();
  if (!picked.length) return;
  pushUndo();
  let z = nextZ();
  for (const element of picked) element.z = z++;
  renderCanvas();
  app.scheduleProjectSave();
}

function sendToBack() {
  const picked = selectedElements();
  if (!picked.length) return;
  pushUndo();
  let z = 0;
  for (const element of picked) element.z = z++;
  renderCanvas();
  app.scheduleProjectSave();
}

function onCanvasKeyDown(event) {
  if (isTypingTarget(event.target)) return;
  const key = event.key.toLowerCase();
  if ((event.ctrlKey || event.metaKey) && key === "z") {
    event.preventDefault();
    if (event.shiftKey) redo(); else undo();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && key === "y") {
    event.preventDefault();
    redo();
    return;
  }
  if (event.key === "Delete" || event.key === "Backspace") {
    event.preventDefault();
    deleteSelection();
    return;
  }
  if (event.key === "Escape") {
    canvas.selection = [];
    renderCanvas();
    return;
  }
  const step = event.shiftKey ? 20 : 4;
  if (event.key === "ArrowLeft") { event.preventDefault(); nudgeSelection(-step, 0); return; }
  if (event.key === "ArrowRight") { event.preventDefault(); nudgeSelection(step, 0); return; }
  if (event.key === "ArrowUp") { event.preventDefault(); nudgeSelection(0, -step); return; }
  if (event.key === "ArrowDown") { event.preventDefault(); nudgeSelection(0, step); return; }
  if (key === "v") { setMode("select"); return; }
  if (key === "n") { setMode("note"); return; }
  if (key === "b") { setMode("draw"); return; }
  if (key === "0") { zoomToFit(); return; }
  if (key === "=" || key === "+") { setZoom(viewport().zoom * 1.15); return; }
  if (key === "-") { setZoom(viewport().zoom / 1.15); }
}

// ---------------------------------------------------------------------------
// Inspector
// ---------------------------------------------------------------------------

function updateInspector() {
  const picked = selectedElements();
  const has = picked.length > 0;
  dom.selectionInfo.textContent = has
    ? `已选中 ${picked.length} 项：${picked.map((element) => describeElement(element)).join("、")}`
    : "选择画布中的内容";
  dom.btnModel.disabled = !has;
  dom.btnToChat.disabled = !has;
  dom.btnFront.disabled = !has;
  dom.btnBack.disabled = !has;
  dom.btnDelete.disabled = !has;
  renderVersionList();
  updateContextLabel();
}

function describeElement(element) {
  if (element.type === "note") return "便签";
  if (element.type === "stroke") return "笔迹";
  if (element.type === "model") return element.label || "3D 模型";
  return element.caption || "图片";
}

function renderVersionList() {
  const host = dom.versionList;
  if (!host) return;
  host.replaceChildren();
  const versions = app.state.modelVersions || [];
  if (!versions.length) {
    const empty = document.createElement("p");
    empty.className = "inspector-empty";
    empty.textContent = "还没有模型版本";
    host.appendChild(empty);
    return;
  }
  versions.forEach((version, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = version.id === app.state.activeVersionId ? "active" : "";
    button.textContent = `V${index + 1} · ${version.engine || "模型"}`;
    button.title = version.prompt || version.meshUrl || "";
    button.addEventListener("click", () => {
      app.switchModelVersion(version.id);
      renderVersionList();
    });
    host.appendChild(button);
  });
}

// ---------------------------------------------------------------------------
// Conversation
// ---------------------------------------------------------------------------

function messages() {
  if (!app.state.messages) app.state.messages = [];
  return app.state.messages;
}

function addMessage(message) {
  const entry = { createdAt: Date.now(), ...message };
  messages().push(entry);
  if (messages().length > 200) messages().splice(0, messages().length - 200);
  renderConversation();
  app.scheduleProjectSave();
  return entry;
}

function renderConversation() {
  const host = dom.conversation;
  if (!host) return;
  host.replaceChildren();
  const list = messages();
  if (!list.length) {
    const empty = document.createElement("div");
    empty.className = "conversation-empty";
    empty.textContent = "描述一个想法，AI 会先生成几张预览供你挑选。";
    host.appendChild(empty);
    updateContextLabel();
    return;
  }
  for (const message of list) host.appendChild(renderMessage(message));
  host.scrollTop = host.scrollHeight;
  updateContextLabel();
}

function renderMessage(message) {
  const wrapper = document.createElement("div");
  wrapper.className = `chat-message ${message.role}${message.kind === "error" ? " error" : ""}`;
  const body = document.createElement("p");
  body.textContent = message.content || "";
  wrapper.appendChild(body);

  if (message.kind === "previews" && Array.isArray(message.previews)) {
    const grid = document.createElement("div");
    grid.className = "chat-preview-grid";
    message.previews.forEach((preview, index) => {
      const card = document.createElement("div");
      card.className = "chat-preview";
      const picture = document.createElement("img");
      picture.src = preview.path;
      picture.alt = preview.caption || `预览 ${index + 1}`;
      picture.loading = "lazy";
      const label = document.createElement("div");
      label.className = "chat-preview-label";
      label.textContent = preview.caption || `方案 ${index + 1}`;
      const actions = document.createElement("div");
      actions.className = "chat-preview-actions";
      const addButton = document.createElement("button");
      addButton.type = "button";
      addButton.textContent = "放入画布";
      addButton.addEventListener("click", () => addPreviewToCanvas(preview, message));
      const modelButton = document.createElement("button");
      modelButton.type = "button";
      modelButton.textContent = "生成 3D";
      modelButton.addEventListener("click", () => generateFromPreview(preview, message));
      actions.appendChild(addButton);
      actions.appendChild(modelButton);
      card.appendChild(picture);
      card.appendChild(label);
      card.appendChild(actions);
      grid.appendChild(card);
    });
    wrapper.appendChild(grid);
  }

  if (message.kind === "error" && message.retryPrompt) {
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "chat-retry";
    retry.textContent = "重试";
    retry.addEventListener("click", () => {
      dom.chatInput.value = message.retryPrompt;
      dom.chatInput.focus();
    });
    wrapper.appendChild(retry);
  }

  const meta = document.createElement("span");
  meta.className = "chat-message-meta";
  meta.textContent = message.createdAt ? new Date(message.createdAt).toLocaleTimeString() : "";
  wrapper.appendChild(meta);
  return wrapper;
}

function updateContextLabel() {
  const versions = app.state.modelVersions || [];
  const active = versions.find((version) => version.id === app.state.activeVersionId);
  const selected = selectedElements()[0];
  if (selected) {
    dom.contextLabel.textContent = `画布：${describeElement(selected)}`;
    return;
  }
  dom.contextLabel.textContent = active
    ? `当前版本 V${versions.indexOf(active) + 1} · ${active.engine || "模型"}`
    : "新作品";
}

// ---------------------------------------------------------------------------
// Generation flow
// ---------------------------------------------------------------------------

function randomSessionId() {
  if (window.crypto && window.crypto.randomUUID) {
    return window.crypto.randomUUID().replace(/-/g, "").slice(0, 12);
  }
  return Math.random().toString(16).slice(2, 14);
}

async function submitChat(event) {
  event.preventDefault();
  const text = dom.chatInput.value.trim();
  if (!text) return;
  dom.chatInput.value = "";
  addMessage({ role: "user", content: text });
  app.state.currentPrompt = text;
  await runPreviewGeneration(text);
}

async function runPreviewGeneration(text) {
  const status = addMessage({ role: "assistant", kind: "status", content: "正在理解你的想法…" });
  const sid = randomSessionId();
  try {
    const response = await fetch("/api/previews_v2", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: text, n: 4, prefer: "aixj", session_id: sid }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const queued = await response.json();
    const activeSid = queued.session_id || sid;
    await pollPreviewProgress(activeSid, status);
    const result = await fetch(`/api/session/${activeSid}/result`);
    if (result.status === 202) throw new Error("预览仍在生成，请稍后重试");
    if (!result.ok) throw new Error(`HTTP ${result.status}`);
    const payload = await result.json();
    const previews = (payload.previews || []).map((preview) => ({
      path: preview.path,
      caption: (payload.specs && payload.specs[preview.index] && payload.specs[preview.index].caption) || `方案 ${preview.index + 1}`,
      index: preview.index,
      sessionId: activeSid,
    }));
    if (!previews.length) throw new Error("这次没有生成出可用预览");
    app.state.previews = previews.map((preview) => ({ ...preview, session_id: activeSid }));
    app.state.previewSessionId = activeSid;
    app.state.selectedIndex = 0;
    status.kind = "previews";
    status.content = `已经生成 ${previews.length} 张预览，选一张继续，或者先放入画布再调整。`;
    status.previews = previews;
    renderConversation();
    app.renderPreviews();
    app.scheduleProjectSave();
  } catch (error) {
    status.kind = "error";
    status.content = `生成失败：${error.message}`;
    status.retryPrompt = text;
    renderConversation();
  }
}

async function pollPreviewProgress(sid, status) {
  const started = Date.now();
  let lastText = "";
  while (Date.now() - started < 600000) {
    try {
      const response = await fetch(`/api/progress/${sid}`);
      if (response.ok) {
        const payload = await response.json();
        const latest = payload.latest || {};
        const text = latest.message || latest.step || "";
        if (text && text !== lastText) {
          lastText = text;
          status.content = text;
          renderConversation();
        }
        if (latest.step === "done" || latest.step === "failed") break;
      }
    } catch (error) {
      /* a transient polling failure must not abort the generation */
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}

function addPreviewToCanvas(preview, message) {
  if (elements().length >= MAX_ELEMENTS) {
    window.alert("画布内容已达上限，请先删除一些内容");
    return;
  }
  pushUndo();
  const offset = (elements().length % 6) * 18;
  const element = {
    id: uid("preview"),
    type: "preview",
    x: -PREVIEW_WIDTH / 2 + offset,
    y: -PREVIEW_HEIGHT / 2 + offset,
    width: PREVIEW_WIDTH,
    height: PREVIEW_HEIGHT,
    z: nextZ(),
    path: preview.path,
    caption: preview.caption || "预览",
    sessionId: preview.sessionId || app.state.previewSessionId,
    imageIndex: preview.index ?? 0,
  };
  elements().push(element);
  canvas.selection = [element.id];
  renderCanvas();
  app.scheduleProjectSave();
  if (message) {
    message.content = `${message.content} 已把 1 张预览放入画布。`;
    renderConversation();
  }
}

function addModelToCanvas(version, index) {
  pushUndo();
  const element = {
    id: uid("model"),
    type: "model",
    x: -PREVIEW_WIDTH / 2 + index * 24,
    y: -60 + index * 24,
    width: PREVIEW_WIDTH,
    height: 120,
    z: nextZ(),
    label: `V${index + 1} · ${version.engine || "模型"}`,
    detail: version.prompt || "点击打开 3D 编辑器",
    versionId: version.id,
    sid: version.sid,
    meshUrl: version.meshUrl,
  };
  elements().push(element);
  canvas.selection = [element.id];
  renderCanvas();
  app.scheduleProjectSave();
}

async function generateFromPreview(preview, message) {
  const sessionId = preview.sessionId || app.state.previewSessionId;
  const imageIndex = preview.index ?? 0;
  const status = addMessage({ role: "assistant", kind: "status", content: "正在生成 3D 模型…" });
  try {
    const result = await app.generateModel({
      sessionId,
      imageIndex,
      engine: selectedEngine(),
      prompt: app.state.currentPrompt || "",
      report: (text) => {
        status.content = text;
        renderConversation();
      },
    });
    status.kind = "versions";
    status.content = `已生成模型版本（${result.engine}）。可以在右侧切换版本，或点击模型卡片进入 3D 编辑。`;
    addModelToCanvas(result.version, (app.state.modelVersions || []).length - 1);
    renderConversation();
  } catch (error) {
    status.kind = "error";
    status.content = `3D 生成失败：${error.message}`;
    renderConversation();
  }
}

function selectedEngine() {
  const select = dom.engineSelect;
  if (select && select.value) return select.value;
  const checked = document.querySelector('input[name="engine"]:checked');
  return checked ? checked.value : "cartoon";
}

async function generateFromCanvasSelection() {
  const picked = selectedElements();
  const visual = picked.filter((element) => element.type === "preview" || element.type === "image");
  if (!visual.length) {
    window.alert("请先在画布上选择一张预览或图片");
    return;
  }
  const status = addMessage({ role: "assistant", kind: "status", content: "正在把画布内容合成建模输入…" });
  try {
    const composed = await composeCanvasImage(visual);
    const response = await fetch("/api/session/from-image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image: composed.png,
        svg: composed.svg,
        prompt: app.state.currentPrompt || "",
        source: "canvas",
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const created = await response.json();
    const result = await app.generateModel({
      sessionId: created.session_id,
      imageIndex: 0,
      engine: selectedEngine(),
      prompt: app.state.currentPrompt || "",
      report: (text) => {
        status.content = text;
        renderConversation();
      },
    });
    status.kind = "versions";
    status.content = `画布合成图已用于建模（${result.engine}）。`;
    addModelToCanvas(result.version, (app.state.modelVersions || []).length - 1);
    renderConversation();
  } catch (error) {
    status.kind = "error";
    status.content = `画布建模失败：${error.message}`;
    renderConversation();
  }
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`图片加载失败：${src}`));
    image.src = src;
  });
}

/**
 * Flatten the selected canvas elements into one PNG (plus an SVG wrapper)
 * that becomes the real image-to-3D input.
 */
async function composeCanvasImage(visual) {
  const bounds = boundsOf(visual);
  const padding = 24;
  const scale = Math.min(
    1024 / Math.max(bounds.width + padding * 2, 1),
    1024 / Math.max(bounds.height + padding * 2, 1),
    4,
  );
  const width = Math.max(64, Math.round((bounds.width + padding * 2) * scale));
  const height = Math.max(64, Math.round((bounds.height + padding * 2) * scale));
  const surface = document.createElement("canvas");
  surface.width = width;
  surface.height = height;
  const context = surface.getContext("2d");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);

  const ordered = visual.slice().sort((a, b) => (Number(a.z) || 0) - (Number(b.z) || 0));
  for (const element of ordered) {
    const left = ((Number(element.x) || 0) - bounds.x + padding) * scale;
    const top = ((Number(element.y) || 0) - bounds.y + padding) * scale;
    const elementWidth = (Number(element.width) || PREVIEW_WIDTH) * scale;
    const elementHeight = (Number(element.height) || PREVIEW_HEIGHT) * scale;
    if (element.type === "stroke") {
      const points = Array.isArray(element.points) ? element.points : [];
      if (points.length < 2) continue;
      context.strokeStyle = element.strokeColor || "#2676c9";
      context.lineWidth = (Number(element.strokeWidth) || 4) * scale;
      context.lineCap = "round";
      context.lineJoin = "round";
      context.beginPath();
      points.forEach((point, index) => {
        const x = left + (Number(point[0]) || 0) * scale;
        const y = top + (Number(point[1]) || 0) * scale;
        if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
      });
      context.stroke();
      continue;
    }
    if (element.type === "note") {
      context.fillStyle = "#fff3b0";
      context.fillRect(left, top, elementWidth, elementHeight);
      context.fillStyle = "#463f2d";
      context.font = `${Math.max(12, Math.round(14 * scale))}px sans-serif`;
      (element.text || "").split("\n").slice(0, 8).forEach((line, index) => {
        context.fillText(line, left + 8 * scale, top + (20 + index * 18) * scale);
      });
      continue;
    }
    try {
      const image = await loadImage(element.path);
      context.drawImage(image, left, top, elementWidth, elementHeight);
    } catch (error) {
      context.fillStyle = "#e6ecf2";
      context.fillRect(left, top, elementWidth, elementHeight);
    }
  }

  const png = surface.toDataURL("image/png");
  return { png, svg: buildEmbeddedSvg(surface, width, height), width, height };
}

function buildEmbeddedSvg(surface, width, height) {
  const png = surface.toDataURL("image/png");
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
    "<!-- 内嵌位图，不是矢量轮廓；切割前请在软件中确认描线 -->",
    `<image href="${png}" x="0" y="0" width="${width}" height="${height}"/>`,
    "</svg>",
  ].join("");
}

// ---------------------------------------------------------------------------
// Voice input
// ---------------------------------------------------------------------------

function setVoiceStatus(text, tone = "") {
  dom.voiceStatus.textContent = text;
  dom.voiceStatus.dataset.tone = tone;
}

function stopVoice() {
  if (voice.recognition) {
    try { voice.recognition.stop(); } catch (error) { /* already stopped */ }
  }
  voice.recognition = null;
  voice.listening = false;
  voice.lastApplied = null;
  dom.btnVoice.classList.remove("active");
  dom.btnVoice.setAttribute("aria-pressed", "false");
  dom.btnVoice.textContent = "语音";
}

function startVoice() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    setVoiceStatus("当前浏览器不支持语音识别，请直接输入文字", "error");
    return;
  }
  if (voice.listening) {
    stopVoice();
    return;
  }
  const area = dom.chatInput;
  voice.baseText = area.value;
  voice.startText = area.value;
  voice.finalized = "";
  voice.lastApplied = area.value;
  const recognition = new Recognition();
  recognition.lang = "zh-CN";
  recognition.interimResults = true;
  recognition.continuous = true;
  recognition.maxAlternatives = 1;

  recognition.onresult = (event) => {
    // The user may type while recognition is running. When the field no
    // longer matches what we last wrote, their text becomes the new base so
    // the next result can never overwrite it.
    const userEdited = voice.lastApplied !== null && area.value !== voice.lastApplied;
    if (userEdited) {
      voice.baseText = area.value;
      voice.finalized = "";
    }
    let interim = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      const transcript = result[0] ? result[0].transcript : "";
      if (result.isFinal) voice.finalized += transcript;
      else interim += transcript;
    }
    const combined = [voice.baseText, voice.finalized, interim].filter(Boolean).join("");
    area.focus();
    const scrollTop = area.scrollTop;
    area.value = combined;
    voice.lastApplied = combined;
    // Keep the caret behind the user's own text after a manual edit, and at
    // the end of the recognised text otherwise.
    const caret = userEdited ? voice.baseText.length : combined.length;
    area.setSelectionRange(caret, caret);
    area.scrollTop = scrollTop;
    setVoiceStatus("正在聆听…（说完点“语音”停止）", "active");
  };
  recognition.onerror = (event) => {
    const messages = {
      "not-allowed": "麦克风权限被拒绝，请改用键盘输入",
      "no-speech": "没有听到声音，请再试一次",
      "network": "语音识别网络中断，请改用键盘输入",
      "audio-capture": "找不到麦克风，请改用键盘输入",
      "aborted": "语音识别已停止",
    };
    setVoiceStatus(messages[event.error] || `语音识别出错：${event.error}`, "error");
    stopVoice();
  };
  recognition.onend = () => {
    if (voice.recognition === recognition) {
      voice.recognition = null;
      voice.listening = false;
      dom.btnVoice.classList.remove("active");
      dom.btnVoice.setAttribute("aria-pressed", "false");
      dom.btnVoice.textContent = "语音";
      if (area.value === voice.startText) {
        setVoiceStatus("没有识别到内容，请再试一次或改用键盘输入", "error");
      } else {
        setVoiceStatus("识别完成，文字已留在输入框，可继续编辑后发送");
      }
    }
  };

  voice.recognition = recognition;
  voice.listening = true;
  dom.btnVoice.classList.add("active");
  dom.btnVoice.setAttribute("aria-pressed", "true");
  dom.btnVoice.textContent = "停止";
  setVoiceStatus("正在聆听…", "active");
  try {
    recognition.start();
  } catch (error) {
    setVoiceStatus("语音识别启动失败，请改用键盘输入", "error");
    stopVoice();
  }
}

// ---------------------------------------------------------------------------
// Prompt polish
// ---------------------------------------------------------------------------

async function polishPrompt() {
  const original = dom.chatInput.value;
  if (!original.trim()) {
    setPolishMessage("请先写一句描述，再进行润色", true);
    return;
  }
  dom.btnPolish.disabled = true;
  setPolishMessage("正在生成润色建议…", false);
  try {
    const response = await fetch("/api/prompt/polish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: original }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (payload.ok && payload.suggestion) {
      dom.polishText.textContent = payload.suggestion;
      dom.polishPreview.hidden = false;
      dom.polishPreview.dataset.source = "cloud";
      setPolishMessage("已生成云端润色建议，确认后再替换原文", false);
      return;
    }
    if (payload.fallback && payload.fallback.text) {
      dom.polishText.textContent = payload.fallback.text;
      dom.polishPreview.hidden = false;
      dom.polishPreview.dataset.source = "local";
      setPolishMessage("云端润色不可用，已改用本机规则建议（未发送你的文字）", false);
      return;
    }
    setPolishMessage("润色服务暂时不可用，原文已保留", true);
  } catch (error) {
    setPolishMessage(`润色失败：${error.message}，原文已保留`, true);
  } finally {
    dom.btnPolish.disabled = false;
  }
}

function setPolishMessage(text, isError) {
  if (!dom.polishMessage) return;
  dom.polishMessage.textContent = text;
  dom.polishMessage.dataset.tone = isError ? "error" : "info";
}

function applyPolish() {
  const suggestion = dom.polishText.textContent || "";
  if (!suggestion) return;
  dom.chatInput.value = suggestion;
  dom.chatInput.focus();
  dom.polishPreview.hidden = true;
  setPolishMessage("已应用润色建议，发送前仍可手动修改", false);
}

function dismissPolish() {
  dom.polishPreview.hidden = true;
  setPolishMessage("已放弃润色建议，原文未改动", false);
}

// ---------------------------------------------------------------------------
// Canvas -> chat
// ---------------------------------------------------------------------------

function bringSelectionToChat() {
  const picked = selectedElements();
  if (!picked.length) return;
  const descriptions = picked.map((element) => {
    if (element.type === "note") return `便签：${element.text || "（空）"}`;
    if (element.type === "model") return `模型版本：${element.label || ""}`;
    if (element.type === "stroke") return "自由笔迹标注";
    return `素材：${element.caption || "图片"}`;
  });
  const context = descriptions.join("；");
  dom.chatInput.value = dom.chatInput.value
    ? `${dom.chatInput.value}（参考${context}）`
    : `参考${context}，请在这个基础上继续创作`;
  dom.chatInput.focus();
  app.state.currentPrompt = dom.chatInput.value;
  app.scheduleProjectSave();
  updateContextLabel();
}

// ---------------------------------------------------------------------------
// Delivery to desktop software
// ---------------------------------------------------------------------------

async function refreshSoftware() {
  try {
    const response = await fetch("/api/software/detect");
    if (!response.ok) throw new Error("HTTP " + response.status);
    const payload = await response.json();
    renderSoftware(payload.tools || []);
  } catch (error) {
    dom.softwareStatus.textContent = `软件检测失败：${error.message}`;
    dom.softwareStatus.dataset.tone = "error";
  }
}

function renderSoftware(tools) {
  const host = dom.softwareList;
  host.replaceChildren();
  const interesting = tools.filter((tool) => (
    ["bambu", "xtool", "orca", "prusa", "cura", "blender", "lightburn"].includes(tool.id)
  ));
  if (!interesting.length) {
    dom.softwareStatus.textContent = "没有检测到可用的桌面软件";
    dom.softwareStatus.dataset.tone = "warn";
    return;
  }
  let available = 0;
  for (const tool of interesting) {
    const row = document.createElement("div");
    row.className = `software-row${tool.available ? " available" : ""}`;
    const name = document.createElement("strong");
    name.textContent = tool.name;
    const detail = document.createElement("span");
    const verified = tool.verifiedFormats || [];
    if (tool.overrideMissing) {
      detail.textContent = `自定义路径失效 · ${tool.override}`;
    } else if (tool.available) {
      detail.textContent = verified.length
        ? `已检测 · 已验证 ${verified.map((fmt) => fmt.toUpperCase()).join(" / ")}`
        : `已检测 · ${tool.formats.join(" / ")}`;
    } else {
      detail.textContent = `未检测到 · 支持 ${tool.formats.join(" / ")}`;
    }
    row.appendChild(name);
    row.appendChild(detail);
    if (tool.available) {
      available += 1;
      const open = document.createElement("button");
      open.type = "button";
      open.className = "mini-btn";
      open.textContent = "打开当前作品";
      open.addEventListener("click", () => prepareDelivery(tool, row));
      row.appendChild(open);
    }
    row.appendChild(buildSoftwarePathEditor(tool));
    host.appendChild(row);
  }
  dom.softwareStatus.textContent = available
    ? `已检测 ${available} 个可用软件`
    : "没有检测到可用的桌面软件";
  dom.softwareStatus.dataset.tone = available ? "ok" : "warn";
}

function buildSoftwarePathEditor(tool) {
  const editor = document.createElement("div");
  editor.className = "software-path-editor";

  const input = document.createElement("input");
  input.type = "text";
  input.value = tool.path || tool.override || "";
  input.placeholder = "软件可执行文件路径，例如 C:\\Program Files\\Bambu Studio\\bambu-studio.exe";
  input.setAttribute("aria-label", `${tool.name} 可执行文件路径`);
  input.className = "software-path-input";

  const save = document.createElement("button");
  save.type = "button";
  save.className = "mini-btn";
  save.textContent = "保存路径";
  save.addEventListener("click", async () => {
    const value = input.value.trim();
    if (!value) {
      dom.softwareStatus.textContent = "请先填写软件可执行文件路径";
      dom.softwareStatus.dataset.tone = "warn";
      return;
    }
    save.disabled = true;
    try {
      const response = await fetch("/api/software/path", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ software_id: tool.id, path: value }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      renderSoftware(payload.tools || []);
      dom.softwareStatus.textContent = `已保存 ${tool.name} 的路径`;
      dom.softwareStatus.dataset.tone = "ok";
    } catch (error) {
      dom.softwareStatus.textContent = `保存路径失败：${error.message}`;
      dom.softwareStatus.dataset.tone = "error";
      save.disabled = false;
    }
  });

  const reset = document.createElement("button");
  reset.type = "button";
  reset.className = "mini-btn";
  reset.textContent = "恢复自动检测";
  reset.addEventListener("click", async () => {
    reset.disabled = true;
    try {
      const response = await fetch(`/api/software/path/${encodeURIComponent(tool.id)}`, {
        method: "DELETE",
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      renderSoftware(payload.tools || []);
      dom.softwareStatus.textContent = `已恢复 ${tool.name} 的自动检测`;
      dom.softwareStatus.dataset.tone = "info";
    } catch (error) {
      dom.softwareStatus.textContent = `恢复自动检测失败：${error.message}`;
      dom.softwareStatus.dataset.tone = "error";
      reset.disabled = false;
    }
  });

  editor.appendChild(input);
  editor.appendChild(save);
  editor.appendChild(reset);
  return editor;
}

function prepareDelivery(tool, row) {
  const existing = row.querySelector(".delivery-confirm");
  if (existing) {
    existing.remove();
    return;
  }
  const version = (app.state.modelVersions || []).find((entry) => entry.id === app.state.activeVersionId);
  const target = describeDeliveryTarget(tool, version);
  const confirmBox = document.createElement("div");
  confirmBox.className = "delivery-confirm";
  const label = document.createElement("p");
  label.textContent = `即将用 ${tool.name} 打开 ${target.name}`;
  const hint = document.createElement("p");
  hint.textContent = tool.kind === "laser"
    ? "只打开设计文件，不会自动开始切割。"
    : "只打开模型文件，不会自动切片或打印。";
  const confirm = document.createElement("button");
  confirm.type = "button";
  confirm.className = "mini-btn primary";
  confirm.textContent = "确认打开";
  confirm.addEventListener("click", () => {
    confirmBox.remove();
    openInSoftware(tool);
  });
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "mini-btn";
  cancel.textContent = "取消";
  cancel.addEventListener("click", () => confirmBox.remove());
  confirmBox.appendChild(label);
  confirmBox.appendChild(hint);
  confirmBox.appendChild(confirm);
  confirmBox.appendChild(cancel);
  row.appendChild(confirmBox);
}

function describeDeliveryTarget(tool, version) {
  if (tool.kind === "laser") {
    return { name: "画布合成图 PNG" };
  }
  if (!version) {
    return { name: "当前模型 STL" };
  }
  const index = (app.state.modelVersions || []).indexOf(version) + 1;
  return { name: `模型版本 V${index} 的 STL` };
}

async function openInSoftware(tool) {
  const version = (app.state.modelVersions || []).find((entry) => entry.id === app.state.activeVersionId);
  const sid = version ? version.sid : app.state.sid;
  if (!sid) {
    dom.softwareStatus.textContent = "还没有可交付的模型，请先生成一个版本";
    dom.softwareStatus.dataset.tone = "warn";
    return;
  }
  if (tool.kind !== "laser") {
    try {
      if (app.canPersistEditedModel()) await app.persistEditedModel();
    } catch (error) {
      dom.softwareStatus.textContent = `导出当前编辑结果失败：${error.message}`;
      dom.softwareStatus.dataset.tone = "error";
      return;
    }
  }
  if (tool.kind === "laser") {
    const composed = await composeLaserImage();
    if (!composed) {
      dom.softwareStatus.textContent = "画布上没有可用于切割的图片，请先放入预览或导入图片";
      dom.softwareStatus.dataset.tone = "warn";
      return;
    }
    await deliverSession(tool, "png", composed.session_id);
    return;
  }
  await deliverSession(tool, "stl", sid);
}

async function composeLaserImage() {
  const visual = elements().filter((element) => element.type === "preview" || element.type === "image");
  if (!visual.length) return null;
  const composed = await composeCanvasImage(visual);
  const response = await fetch("/api/session/from-image", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      image: composed.png,
      svg: composed.svg,
      prompt: app.state.currentPrompt || "",
      source: "canvas-laser",
    }),
  });
  if (!response.ok) return null;
  return response.json();
}

async function deliverSession(tool, fmt, sid) {
  dom.softwareStatus.textContent = `正在把文件交给 ${tool.name}…`;
  dom.softwareStatus.dataset.tone = "info";
  try {
    const response = await fetch("/api/software/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ software_id: tool.id, session_id: sid, fmt, image_index: 0 }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const payload = await response.json();
    dom.softwareStatus.textContent = `已把 ${payload.file || "文件"} 交给 ${tool.name}，请在软件中确认后再打印或切割`;
    dom.softwareStatus.dataset.tone = "ok";
  } catch (error) {
    dom.softwareStatus.textContent = `打开失败：${error.message}`;
    dom.softwareStatus.dataset.tone = "error";
  }
}

// ---------------------------------------------------------------------------
// Image import
// ---------------------------------------------------------------------------

async function importCanvasImage(file) {
  if (!file) return;
  try {
    if (!app.state.projectId) await app.saveProject({ automatic: true });
    if (!app.state.projectId) throw new Error("项目尚未保存，无法接收图片");
    const body = new FormData();
    body.append("image", file, file.name);
    const response = await fetch(`/api/projects/${encodeURIComponent(app.state.projectId)}/media`, {
      method: "POST",
      body,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const media = await response.json();
    pushUndo();
    const element = {
      id: uid("image"),
      type: "image",
      x: -PREVIEW_WIDTH / 2,
      y: -PREVIEW_HEIGHT / 2,
      width: PREVIEW_WIDTH,
      height: Math.round(PREVIEW_HEIGHT * (media.height / Math.max(media.width, 1))),
      z: nextZ(),
      path: media.path,
      caption: file.name || "导入图片",
    };
    elements().push(element);
    canvas.selection = [element.id];
    renderCanvas();
    app.scheduleProjectSave();
  } catch (error) {
    window.alert(`图片导入失败：${error.message}`);
  }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

export function initWorkbench(context) {
  app = context;
  dom = {
    viewport: $("#canvas-viewport"),
    world: $("#canvas-world"),
    empty: $("#canvas-empty"),
    marquee: null,
    zoomLabel: $("#canvas-zoom-label"),
    itemCount: $("#canvas-item-count"),
    selectionInfo: $("#canvas-selection-info"),
    versionList: $("#workbench-model-versions"),
    toolSelect: $("#btn-canvas-pan"),
    toolNote: $("#btn-canvas-note"),
    toolDraw: $("#btn-canvas-draw"),
    strokeColor: $("#canvas-stroke-color"),
    strokeWidth: $("#canvas-stroke-width"),
    btnModel: $("#btn-canvas-model"),
    btnToChat: $("#btn-canvas-to-chat"),
    btnFront: $("#btn-canvas-front"),
    btnBack: $("#btn-canvas-back"),
    btnDelete: $("#btn-canvas-delete"),
    btnUndo: $("#btn-canvas-undo"),
    btnRedo: $("#btn-canvas-redo"),
    btnFit: $("#btn-canvas-fit"),
    btnReset: $("#btn-canvas-reset"),
    imageInput: $("#canvas-image-input"),
    conversation: $("#conversation-list"),
    contextLabel: $("#chat-context-label"),
    chatForm: $("#chat-form"),
    chatInput: $("#chat-input"),
    btnVoice: $("#btn-chat-voice"),
    btnPolish: $("#btn-chat-polish"),
    btnChatClear: $("#btn-chat-clear"),
    voiceStatus: $("#voice-status"),
    polishPreview: $("#chat-polish-preview"),
    polishText: $("#chat-polish-text"),
    polishApply: $("#btn-polish-apply"),
    polishDismiss: $("#btn-polish-dismiss"),
    polishMessage: $("#chat-polish-message"),
    title: $("#workbench-project-title"),
    btnSave: $("#btn-workbench-save"),
    btnLibrary: $("#btn-library-workbench"),
    engineSelect: $("#workbench-engine"),
    softwareList: $("#workbench-software-list"),
    softwareStatus: $("#workbench-software-status"),
  };

  if (!dom.viewport || !dom.world) return;

  dom.viewport.addEventListener("pointerdown", onPointerDown);
  dom.viewport.addEventListener("pointermove", onPointerMove);
  dom.viewport.addEventListener("pointerup", onPointerUp);
  dom.viewport.addEventListener("pointercancel", onPointerUp);
  dom.viewport.addEventListener("wheel", onWheel, { passive: false });
  document.addEventListener("keydown", (event) => {
    if (event.code === "Space" && !isTypingTarget(event.target)) canvas.spaceDown = true;
  });
  document.addEventListener("keyup", (event) => {
    if (event.code === "Space") canvas.spaceDown = false;
  });
  document.addEventListener("keydown", (event) => {
    if (!dom.viewport.closest(".step") || !dom.viewport.closest(".step").classList.contains("active")) return;
    onCanvasKeyDown(event);
  });

  dom.toolSelect.addEventListener("click", () => setMode("select"));
  dom.toolNote.addEventListener("click", () => setMode("note"));
  dom.toolDraw.addEventListener("click", () => setMode("draw"));
  dom.btnUndo.addEventListener("click", undo);
  dom.btnRedo.addEventListener("click", redo);
  dom.btnFit.addEventListener("click", zoomToFit);
  dom.btnReset.addEventListener("click", resetView);
  dom.btnFront.addEventListener("click", bringToFront);
  dom.btnBack.addEventListener("click", sendToBack);
  dom.btnDelete.addEventListener("click", deleteSelection);
  dom.btnModel.addEventListener("click", generateFromCanvasSelection);
  dom.btnToChat.addEventListener("click", bringSelectionToChat);
  dom.imageInput.addEventListener("change", async (event) => {
    await importCanvasImage(event.target.files && event.target.files[0]);
    event.target.value = "";
  });

  dom.chatForm.addEventListener("submit", submitChat);
  dom.btnVoice.addEventListener("click", startVoice);
  dom.btnPolish.addEventListener("click", polishPrompt);
  dom.polishApply.addEventListener("click", applyPolish);
  dom.polishDismiss.addEventListener("click", dismissPolish);
  dom.btnChatClear.addEventListener("click", () => {
    app.state.messages = [];
    renderConversation();
    app.scheduleProjectSave();
  });

  dom.btnSave.addEventListener("click", () => app.saveProject());
  dom.btnLibrary.addEventListener("click", () => app.openLibrary());
  dom.title.addEventListener("input", () => {
    const legacy = $("#project-name");
    if (legacy) legacy.value = dom.title.value;
    app.scheduleProjectSave();
  });

  if (dom.engineSelect) {
    dom.engineSelect.addEventListener("change", () => {
      const radio = document.querySelector(`input[name="engine"][value="${dom.engineSelect.value}"]`);
      if (radio) radio.checked = true;
    });
    const checked = document.querySelector('input[name="engine"]:checked');
    if (checked) dom.engineSelect.value = checked.value;
  }

  setMode("select");
  renderCanvas();
  renderConversation();
  refreshSoftware();

  const legacyName = $("#project-name");
  if (legacyName) {
    legacyName.addEventListener("input", () => {
      dom.title.value = legacyName.value;
      app.scheduleProjectSave();
    });
    if (app.state.projectName) dom.title.value = app.state.projectName;
  }
}

export const workbenchInternals = {
  renderCanvas,
  renderConversation,
  zoomToFit,
  composeCanvasImage,
  addPreviewToCanvas,
};
