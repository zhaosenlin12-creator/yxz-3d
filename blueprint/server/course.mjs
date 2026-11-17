// course.mjs - 课程模式：把项目的真实链路（接线/机械/零件/组装/3D 产出）转成分步教程
// 设计原则：
//   1. 教程内容 100% 来自项目数据本身（不是另写一套课程），保证「课程里就是这个项目」；
//   2. 每个步骤都带 preview.tab，点预览直接跳到项目里对应的画面；
//   3. 对话导师可随时答疑、按难度重排内容，改动立刻写回课程。
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { getProject, projects, readBody, requireUser, now, uuid, userCfgs } from "./store.mjs";
import { callLLM } from "./llm.mjs";

const __dir = dirname(fileURLToPath(import.meta.url));
const COURSES_FILE = join(__dir, "data", "courses.json");

const LEVELS = {
  primary: { label: "小学 · 趣味启蒙", minutes: 1.6, tone: "primary" },
  middle: { label: "初中 · 动手实践", minutes: 1.0, tone: "middle" },
  high: { label: "高中 · 工程进阶", minutes: 0.85, tone: "high" },
};

function loadCourses() {
  if (!existsSync(COURSES_FILE)) return {};
  try {
    const all = JSON.parse(readFileSync(COURSES_FILE, "utf8")) || {};
    for (const k of Object.keys(all)) migrateCourse(all[k]);
    return all;
  } catch { return {}; }
}
function saveCourses(all) { writeFileSync(COURSES_FILE, JSON.stringify(all, null, 2), "utf8"); }

const TAB_LABEL = {
  overview: "概览",
  wiring: "接线图",
  mechanical: "机械",
  parts: "零件",
  instructions: "指南",
  studio3d: "3D 工坊",
};

function cleanText(v, fallback = "") {
  if (v == null) return fallback;
  if (typeof v === "string") return v.trim();
  if (typeof v === "object") {
    if (typeof v.text === "string") return v.text.trim();
    try { return JSON.stringify(v); } catch { return fallback; }
  }
  return String(v);
}

function money(n) {
  const x = Number(n || 0);
  if (!Number.isFinite(x) || x <= 0) return "价格待补充";
  return "¥" + (x >= 100 ? x.toFixed(0) : x.toFixed(2));
}

function nodeNameMap(d) {
  const map = {};
  for (const n of d.nodes || []) {
    if (n && n.id) map[n.id] = n.name || n.type || n.id;
  }
  return map;
}

const TAB_PARAM = { overview: "render", wiring: "wiring", mechanical: "mech", parts: "parts", instructions: "instructions" };

function preview(tab, projectId, extra = "") {
  const url = tab === "studio3d"
    ? "/studio#3d"
    : `/project/${projectId}?tab=${TAB_PARAM[tab] || tab}${extra ? "&" + extra : ""}`;
  return { tab, label: TAB_LABEL[tab] || tab, url };
}

// 把旧版 ?focus= 预览链接迁移为原版 bundle 原生支持的 ?tab= 深链
function migrateCourse(c) {
  if (!c) return c;
  for (const ch of c.chapters || []) {
    for (const s of ch.steps || []) {
      if (s.preview && s.preview.tab && (!s.preview.url || String(s.preview.url).includes("?focus="))) {
        s.preview.url = preview(s.preview.tab, c.projectId).url;
      }
    }
  }
  return c;
}

// 按学段改写讲解口吻：同一份项目数据，三种讲法
function voice(level, o) {
  const { primary, middle, high } = o;
  if (level === "primary") return primary || middle;
  if (level === "high") return high || middle;
  return middle;
}

function buildCourse(project, level = "middle") {
  const d = project.data || {};
  const pid = project.id;
  const name = d.projectName || project.projectName || "未命名项目";
  const nodeName = nodeNameMap(d);
  const wires = Array.isArray(d.wiring) ? d.wiring : [];
  const mech = Array.isArray(d.mechanical) ? d.mechanical : [];
  const parts = Array.isArray(d.parts) ? d.parts : [];
  const steps = Array.isArray(d.instructionSteps) ? d.instructionSteps : [];
  const levelMeta = LEVELS[level] || LEVELS.middle;
  const min = (n) => Math.max(3, Math.round(n * levelMeta.minutes));

  const chapters = [];

  // ---------- 第 1 章：认识这个项目 ----------
  const nodeNames = (d.nodes || []).map((n) => n.name || n.type || n.id).filter(Boolean);
  chapters.push({
    id: "c1",
    title: "第 1 章 · 认识这个项目",
    stage: "认识",
    goal: "看懂项目要做什么、由哪些部分组成，并做好开工准备。",
    intro: voice(level, {
      primary: `这个项目的名字叫「${name}」。一句话说，它就是一个能用程序指挥的小装置：你给它想法，它照着动起来。`,
      middle: `项目「${name}」的整体目标：${cleanText(d.projectDescription, "按方案把想法做成可以运行的实物。")}`,
      high: `项目「${name}」：${cleanText(d.projectDescription, "按方案完成结构、电路与程序的整机实现。")}`,
    }),
    steps: [
      {
        id: "c1s1",
        title: "读懂需求",
        goal: "用自己的话说清楚：这个装置给谁用、要完成什么动作。",
        detail: [
          "项目描述：" + cleanText(d.projectDescription, "（项目暂无描述）"),
          voice(level, {
            primary: "把它想成一个会听指令的小帮手：你让它抓东西、搬东西，它就照着做。",
            middle: "把描述拆成三件事：输入（谁来指挥）、处理（谁在做判断）、输出（什么在动）。",
            high: "把需求拆成功能点与约束：控制核心、执行机构、供电方案、可维护性。",
          }),
        ],
        todo: ["在纸上写下 3 个关键词：它是做什么的、给谁用、最酷的一点是什么。"],
        check: ["能不看资料，用 30 秒把这个项目讲给同学听。"],
        preview: preview("overview", pid),
        minutes: min(6),
      },
      {
        id: "c1s2",
        title: "认识系统组成",
        goal: "认出这套装置里的每一个角色，知道它们各自负责什么。",
        detail: [
          nodeNames.length
            ? "这套装置由这些部分组成：" + nodeNames.map((n, i) => `${i + 1}. ${n}`).join("；") + "。"
            : "这套装置的核心组成可以从「零件」页逐条查看。",
          voice(level, {
            primary: "就像一支球队：有人负责大脑（控制板），有人负责出力（电机舵机），还有人负责供电（电池电源）。",
            middle: "按功能分成四类：控制核心、执行器、传感器/模块、电源与结构件。",
            high: "按信号链划分：主控 MCU → 驱动/执行器 → 机械负载；供电按电压域（3.3V / 5V / 12V）分层。",
          }),
        ],
        todo: ["在「概览」的画布上给每个部件点一下，找到它在图里的位置。"],
        check: ["能不看答案说出：主控是哪块、执行器有几个、电源从哪里来。"],
        preview: preview("overview", pid),
        minutes: min(8),
      },
      {
        id: "c1s3",
        title: "开工准备",
        goal: "把工具、耗材和安全规则准备好，避免做到一半停下来找东西。",
        detail: [
          "开工前确认三样东西：稳定的桌面、能正常工作的电脑、以及项目需要的工具。",
          (d.instructionPreamble && cleanText(d.instructionPreamble)) ? "项目说明：" + cleanText(d.instructionPreamble) : "",
        ].filter(Boolean),
        todo: ["清点工具：螺丝刀、镊子、扎带/杜邦线、绝缘胶带。", "把零件按「电子」「结构」「紧固件」三堆分开。"],
        check: ["桌面没有散落的小螺丝；电源适配器电压与方案一致。"],
        preview: preview("instructions", pid),
        minutes: min(6),
      },
    ],
  });

  // ---------- 第 2 章：电路与接线 ----------
  const wireSteps = [];
  wires.slice(0, 8).forEach((w, i) => {
    const sName = nodeName[w.source] || w.source;
    const tName = nodeName[w.target] || w.target;
    wireSteps.push({
      id: "c2s" + (i + 1),
      title: `${sName} → ${tName}`,
      goal: `把 ${sName} 和 ${tName} 按方案接好（${w.protocol || "信号"} / ${w.voltage || "电压待定"}）。`,
      detail: [
        `接线点：${sName} 的「${w.sourcePin || "?"}」接到 ${tName} 的「${w.targetPin || "?"}」。`,
        `信号类型：${w.protocol || "未标注"}；工作电压：${w.voltage || "未标注"}。`,
        voice(level, {
          primary: "记住一句话：电线的两头要接对门牌号，接错了装置就不听话。",
          middle: "接之前先断电；先接电源地（GND），再接信号线，最后接电源正极。",
          high: "遵循「共地优先、信号后接、上电前复核」的顺序；不同电压域之间必须共地并确认电平匹配。",
        }),
      ],
      todo: [`找到 ${sName} 上的 ${w.sourcePin || "对应引脚"}，插好杜邦线。`, `对应接到 ${tName} 的 ${w.targetPin || "对应引脚"}，轻轻拉一下确认不松。`],
      check: ["同色线不混用；接完后对照接线图逐条复核一次。"],
      preview: preview("wiring", pid),
      minutes: min(7),
    });
  });
  if (!wireSteps.length) {
    wireSteps.push({
      id: "c2s1",
      title: "查看接线方案",
      goal: "先读懂这个项目的电路连接关系。",
      detail: ["这个项目暂时没有单独的接线条目，打开接线图页面查看完整连接。"],
      todo: ["在接线图页面逐条数出连接数量。"],
      check: ["能说出电源线和信号线的区别。"],
      preview: preview("wiring", pid),
      minutes: min(6),
    });
  }
  chapters.push({
    id: "c2",
    title: "第 2 章 · 电路与接线",
    stage: "电路",
    goal: "照着接线图把电的部分接对、接稳。",
    intro: voice(level, {
      primary: "这一章我们给装置接上「神经」：电线把命令从大脑送到手脚。",
      middle: "这一章的目标是完成全部电气连接，并保证供电安全、信号正确。",
      high: "本章完成电气连接与供电校核，重点关注电平匹配、共地与过流保护。",
    }),
    steps: wireSteps,
  });

  // ---------- 第 3 章：机械结构 ----------
  const mechSteps = mech.slice(0, 6).map((m, i) => ({
    id: "c3s" + (i + 1),
    title: `${m.name || "结构件"}${m.joint ? "（" + m.joint + "）" : ""}`,
    goal: `做出并装好「${m.name || "结构件"}」，让它能正常转动/固定。`,
    detail: [
      `类型：${m.type || "结构件"}；材料：${m.material || "PLA"}；连接方式：${m.joint || "固定"}`,
      voice(level, {
        primary: "结构件就像骨架和关节，骨头装稳了，动作才好看。",
        middle: "打印件要注意公差：孔太小就扩孔，太松就加垫片，转动处不要硬拧。",
        high: "控制配合公差与打印收缩：转轴孔留 0.2–0.4mm 间隙，受力件提高填充率与壁厚。",
      }),
    ],
    todo: [`按方案准备「${m.name || "结构件"}」的打印件或现成件。`, "先空装一次，确认孔位与相邻件对得上。"],
    check: ["手动转动关节，全程顺滑、不刮蹭。"],
    preview: preview("mechanical", pid),
    minutes: min(10),
  }));
  if (!mechSteps.length) {
    mechSteps.push({
      id: "c3s1",
      title: "查看机械结构",
      goal: "读懂这个项目的结构与关节关系。",
      detail: ["打开机械页，逐个查看结构件、材料和连接方式。"],
      todo: ["数出总共有几个可动关节。"],
      check: ["能指出哪个件是受力最大的。"],
      preview: preview("mechanical", pid),
      minutes: min(8),
    });
  }
  chapters.push({
    id: "c3",
    title: "第 3 章 · 机械结构",
    stage: "结构",
    goal: "把骨架和关节装稳，让动作可控。",
    intro: voice(level, {
      primary: "这一章给装置装上「骨头和关节」。",
      middle: "这一章完成结构件的制作与装配，并检查每个关节的活动范围。",
      high: "本章完成结构装配与运动学检查：关节自由度、干涉区、负载路径。",
    }),
    steps: mechSteps,
  });

  // ---------- 第 4 章：零件与采购 ----------
  const total = parts.reduce((s, p) => s + Number(p.estimatedCost || 0) * Number(p.quantity || 1), 0);
  chapters.push({
    id: "c4",
    title: "第 4 章 · 零件清单与采购",
    stage: "物料",
    goal: "按清单把要买的零件一次买齐，不花冤枉钱。",
    intro: parts.length
      ? `这个项目共有 ${parts.length} 类零件${total > 0 ? "，按方案估算总价约 " + money(total) : "，方案里没有标注单价" }。`
      : "打开「零件」页查看完整清单。",
    steps: [
      {
        id: "c4s1",
        title: "核对清单",
        goal: "确认每一类零件的名称、数量和单价。",
        detail: parts.length
          ? [parts.map((p, i) => `${i + 1}. ${p.name || p.type || "零件"} × ${p.quantity || 1}　${money(p.estimatedCost)}`).join("\n")]
          : ["打开「零件」页查看完整清单。"],
        todo: ["把清单里已经有、需要买的分别打勾。"],
        check: ["数量按方案 +1 备份计算，关键件有备用。"],
        preview: preview("parts", pid),
        minutes: min(8),
      },
      {
        id: "c4s2",
        title: "下单与验货",
        goal: "买对型号，收到货先验再拆封。",
        detail: [
          "下单时逐项核对型号、电压、尺寸，不只看图片。",
          "收货后先点数、再测通断，最后才装机。",
        ],
        todo: ["拍照留存订单与型号。", "用万用表确认电源输出与标称一致。"],
        check: ["所有零件型号与清单一致，没有缺件。"],
        preview: preview("parts", pid),
        minutes: min(6),
      },
    ],
  });

  // ---------- 第 5 章：组装与调试 ----------
  const buildSteps = [];
  steps.slice(0, 8).forEach((s, i) => {
    const subs = Array.isArray(s.subSteps) ? s.subSteps : [];
    buildSteps.push({
      id: "c5s" + (i + 1),
      title: cleanText(s.title, `组装阶段 ${i + 1}`),
      goal: "按方案把这一阶段做完，并当场检查是否到位。",
      detail: subs.length
        ? subs.map((x, j) => `${j + 1}. ${cleanText(x.title, "步骤")}：${cleanText(x.detail, "")}`)
        : [cleanText(s, "按方案完成本阶段装配。")],
      todo: subs.length ? subs.map((x) => cleanText(x.title, "")) : ["按方案逐项完成本阶段。"],
      check: ["每做完一小步就复查一次，不把问题留到最后。"],
      preview: preview("instructions", pid),
      minutes: min(15),
    });
  });
  if (!buildSteps.length) {
    buildSteps.push({
      id: "c5s1",
      title: "按指南组装",
      goal: "跟着组装指南完成整机搭建。",
      detail: ["打开指南页，按顺序完成装配。"],
      todo: ["每完成一个阶段就拍照记录。"],
      check: ["整机可以安全上电，无异味、无过热。"],
      preview: preview("instructions", pid),
      minutes: min(15),
    });
  }
  chapters.push({
    id: "c5",
    title: "第 5 章 · 组装与调试",
    stage: "组装",
    goal: "把前面所有部分合成一台能动的整机。",
    intro: voice(level, {
      primary: "最后一步：把所有零件装成一台真正的机器，然后让它动起来！",
      middle: "按组装指南逐阶段推进，每完成一阶段做一次通电检查。",
      high: "按阶段装配并逐级上电验证：电源 → 主控 → 执行器 → 整机联动。",
    }),
    steps: buildSteps,
  });

  // ---------- 第 6 章：产出（3D 模型 / 激光名片 / 打印） ----------
  chapters.push({
    id: "c6",
    title: "第 6 章 · 数字化产出与实物化",
    stage: "产出",
    goal: "把项目做成可以展示、可以打印的成品：3D 模型、切割名片、实物照片。",
    intro: "项目的最后一步是「产出」：在 3D 工坊里生成模型、导出 STL、做一张激光切割名片，然后打开本机软件直接打印。",
    steps: [
      {
        id: "c6s1",
        title: "生成 3D 模型",
        goal: "用一句话描述，让宜小智把设计稿变成可打印的 3D 模型。",
        detail: [
          "在 3D 工坊里输入一句描述（例：一个白色宇航服小机器人，双手叉腰），先生成预览图。",
          "挑一张最像的，点「生成 3D 模型」，等它跑完就能下载 GLB / STL。",
        ],
        todo: ["生成 4 张预览图并挑出 1 张。", "生成模型并检查尺寸（高约 70mm）。"],
        check: ["模型是单一连通体、底部平整，可以直接切片。"],
        preview: preview("studio3d", pid),
        minutes: min(10),
      },
      {
        id: "c6s2",
        title: "导出一张激光切割名片",
        goal: "生成一张带姓名与作品的切割名片，用本机激光软件打开。",
        detail: [
          "在 3D 工坊「产出」区填写姓名、身份、联系方式，点「导出切割 SVG」。",
          "后端会生成切割红线 / 雕刻绿线 / 定位十字，尺寸以毫米为单位。",
        ],
        todo: ["填写名片信息并导出 SVG。", "在 xTool Studio / LightBurn 里打开检查版面。"],
        check: ["版面没有文字压线，定位十字在页内。"],
        preview: preview("studio3d", pid),
        minutes: min(8),
      },
      {
        id: "c6s3",
        title: "打开本机软件，完成实物",
        goal: "把模型和切割文件送进切片/激光软件，做出真正的作品。",
        detail: [
          "3D 工坊会检测本机已装的 Bambu Studio / Orca / Cura / xTool / LightBurn。",
          "点「用 Bambu Studio 打开」即可带着刚生成的 STL 直接进入切片。",
        ],
        todo: ["打开切片软件，检查摆放与支撑。", "拍照记录成品，回到课程勾选完成。"],
        check: ["成品与课程目标一致，能稳定摆放/使用。"],
        preview: preview("studio3d", pid),
        minutes: min(10),
      },
    ],
  });

  return {
    id: uuid(),
    projectId: pid,
    projectName: name,
    title: `${name} · 项目实战课`,
    subtitle: `${levelMeta.label} · 共 ${chapters.length} 章 ${chapters.reduce((s, c) => s + c.steps.length, 0)} 步`,
    level,
    levelLabel: levelMeta.label,
    createdAt: now(),
    updatedAt: now(),
    summary: cleanText(d.projectDescription, `围绕「${name}」的完整项目课：从看懂方案到做出实物。`),
    outcomes: [
      "能读懂一份工程项目方案（结构 / 电路 / 物料 / 装配）",
      "能照着接线图完成电气连接并安全上电",
      "能完成结构装配与调试",
      "能产出 3D 模型与激光切割文件，对接本机设备",
    ],
    chapters,
    chat: [],
  };
}

function courseFor(projectId) {
  const all = loadCourses();
  return all[projectId] || null;
}

function levelStep(level, dir) {
  const order = ["primary", "middle", "high"];
  const i = order.indexOf(level);
  return order[Math.max(0, Math.min(order.length - 1, i + dir))];
}

const OFFLINE_HINTS = [
  { k: /(接线|电路|电压|电源|gnd|地线)/i, a: "接线顺序记一句：先断电、先接地、再接信号、最后接电源正。接完对照接线图逐条复核，别凭记忆。" },
  { k: /(机械|关节|舵机|尺寸|公差|打印)/i, a: "结构件先空装一次再上螺丝：孔太紧就轻轻扩孔，太松加垫片。转动关节要留 0.2–0.4mm 间隙，不要硬拧。" },
  { k: /(零件|采购|买|价格|清单)/i, a: "采购看三个字段：型号、电压、尺寸。关键件按方案数量 +1 备份，收货先点数再测通断。" },
  { k: /(3d|模型|stl|打印|切片)/i, a: "3D 产出建议走：描述 → 4 张预览 → 挑一张 → 生成模型 → 下载 STL → 用 Bambu Studio 切片。模型要是单一连通体、底部平整。" },
  { k: /(激光|名片|svg|切割)/i, a: "激光名片导出的是毫米单位 SVG：红线切割、绿线雕刻、十字定位。先在 xTool Studio / LightBurn 里预览版面再上机。" },
  { k: /(难|简单|听不懂|详细)/i, a: "想调难度可以直接说「简化一点」或「再专业一点」，我会按学段重排整门课，项目内容不变。" },
];

function offlineReply(message, course) {
  for (const h of OFFLINE_HINTS) if (h.k.test(message)) return h.a;
  const cur = course?.chapters?.[0];
  return `我在这门课里陪你做「${course?.projectName || "这个项目"}」。可以直接问我：接线怎么接、结构怎么装、零件怎么买、3D 模型怎么出；也可以说「简化一点」「再专业一点」「从第 2 章重新讲」，我马上调整课程内容。` + (cur ? "" : "");
}

async function llmReply(user, course, message) {
  const cfg = userCfgs()[user.id];
  if (!cfg || !cfg.provider || !cfg.apiKey) return null;
  const outline = course.chapters.map((c) => ({
    title: c.title,
    goal: c.goal,
    steps: c.steps.map((s) => ({ title: s.title, goal: s.goal })),
  }));
  const system = [
    "你是「蓝智工坊」的项目课导师，面向中小学生讲工程项目。",
    "回答要短、具体、可执行，一次最多 5 句；先给结论，再给一个动手动作。",
    "课程内容来自学生正在做的这个真实项目，不要编造项目里不存在的零件或参数。",
    "如果学生问的内容课程里没有，就坦白说「方案里没写，建议先按 XX 做」。",
    `当前课程：${course.title}（${course.levelLabel}）。`,
    "课程结构：" + JSON.stringify(outline).slice(0, 3000),
  ].join("\n");
  try {
    const text = await callLLM({ provider: cfg.provider, apiKey: cfg.apiKey, baseUrl: cfg.baseUrl, model: cfg.model, system, user: message, maxTokens: 800 });
    return String(text || "").trim() || null;
  } catch {
    return null;
  }
}

export async function handleCourseApi(req, res, url, path, method) {
  const user = requireUser(req, res);
  if (!user) return;

  // 项目库（供课程选择）
  if (path === "/api/studio/projects" && method === "GET") {
    const list = projects().filter((p) => !user || p.userId === user.id);
    const courses = loadCourses();
    res.end(JSON.stringify({
      projects: list.map((p) => ({
        id: p.id,
        name: (p.data && p.data.projectName) || p.projectName || "未命名项目",
        description: (p.data && p.data.projectDescription) || p.projectDescription || "",
        updatedAt: p.updatedAt,
        parts: Array.isArray(p.data?.parts) ? p.data.parts.length : 0,
        hasCourse: !!courses[p.id],
        level: courses[p.id]?.level || null,
      })),
    }));
    return;
  }

  const m = path.match(/^\/api\/studio\/course(?:\/([0-9a-zA-Z-]+))?(?:\/([a-z]+))?$/);
  if (!m) { res.statusCode = 404; res.end(JSON.stringify({ error: "not_found" })); return; }
  const pid = m[1];
  const action = m[2] || "";

  // GET /api/studio/course/<pid>
  if (method === "GET" && pid && !action) {
    const p = getProject(pid);
    if (!p) { res.statusCode = 404; res.end(JSON.stringify({ error: "project_not_found" })); return; }
    if (p.userId !== user.id) { res.statusCode = 403; res.end(JSON.stringify({ error: "forbidden" })); return; }
    const c = courseFor(pid);
    res.end(JSON.stringify({ course: c }));
    return;
  }

  // POST /api/studio/course/<pid>/generate  { level }
  if (method === "POST" && pid && action === "generate") {
    const p = getProject(pid);
    if (!p) { res.statusCode = 404; res.end(JSON.stringify({ error: "project_not_found" })); return; }
    if (p.userId !== user.id) { res.statusCode = 403; res.end(JSON.stringify({ error: "forbidden" })); return; }
    const b = await readBody(req);
    const level = LEVELS[b.level] ? b.level : "middle";
    const course = buildCourse(p, level);
    const all = loadCourses();
    all[pid] = course;
    saveCourses(all);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, course }));
    return;
  }

  // POST /api/studio/course/<pid>/chat  { message }
  if (method === "POST" && pid && action === "chat") {
    const p = getProject(pid);
    const b = await readBody(req);
    const message = String(b.message || "").trim().slice(0, 2000);
    if (!p) { res.statusCode = 404; res.end(JSON.stringify({ error: "project_not_found" })); return; }
    if (p.userId !== user.id) { res.statusCode = 403; res.end(JSON.stringify({ error: "forbidden" })); return; }
    if (!message) { res.statusCode = 400; res.end(JSON.stringify({ error: "empty_message" })); return; }
    let course = courseFor(pid) || buildCourse(p, b.level || "middle");
    let changed = false;

    // 难度指令：直接重排整门课
    if (/(简化|简单一点|简单点|太难|降低难度|听不懂)/.test(message)) {
      const next = levelStep(course.level, -1);
      if (next !== course.level) { course = buildCourse(p, next); changed = true; }
    } else if (/(再难|专业一点|加深|提高难度|进阶|更详细)/.test(message)) {
      const next = levelStep(course.level, +1);
      if (next !== course.level) { course = buildCourse(p, next); changed = true; }
    } else if (/(重新生成|重做|重排课程|换一版)/.test(message)) {
      course = buildCourse(p, course.level);
      changed = true;
    }

    let reply = null;
    if (!changed) reply = await llmReply(user, course, message);
    if (!reply) reply = changed
      ? `已按你的要求把课程重排为「${course.levelLabel}」，项目内容和步骤一一对应，进度已保留在新版本里。`
      : offlineReply(message, course);

    course.chat = Array.isArray(course.chat) ? course.chat : [];
    course.chat.push({ role: "user", content: message, at: now() });
    course.chat.push({ role: "assistant", content: reply, at: now() });
    course.chat = course.chat.slice(-60);
    course.updatedAt = now();
    const all = loadCourses();
    all[pid] = course;
    saveCourses(all);
    res.end(JSON.stringify({ ok: true, reply, courseChanged: changed, course, level: course.level }));
    return;
  }

  // POST /api/studio/course/<pid>/step  { stepId, done }
  if (method === "POST" && pid && action === "step") {
    const b = await readBody(req);
    const p = getProject(pid);
    if (!p) { res.statusCode = 404; res.end(JSON.stringify({ error: "project_not_found" })); return; }
    if (p.userId !== user.id) { res.statusCode = 403; res.end(JSON.stringify({ error: "forbidden" })); return; }
    const all = loadCourses();
    const course = all[pid];
    if (!course) { res.statusCode = 404; res.end(JSON.stringify({ error: "course_not_found" })); return; }
    let found = null;
    for (const c of course.chapters) for (const s of c.steps) if (s.id === b.stepId) found = s;
    if (!found) { res.statusCode = 404; res.end(JSON.stringify({ error: "step_not_found" })); return; }
    found.done = !!b.done;
    found.doneAt = b.done ? now() : null;
    course.updatedAt = now();
    all[pid] = course;
    saveCourses(all);
    res.end(JSON.stringify({ ok: true, course }));
    return;
  }

  res.statusCode = 404;
  res.end(JSON.stringify({ error: "not_found" }));
}

export { buildCourse, loadCourses };
