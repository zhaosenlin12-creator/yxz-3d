// inject.js - 中文界面覆盖层 + 套餐/积分 UI 收敛 + 模型配置面板
// 原则：绝不改动原版 bundle；只做 DOM 层文案替换与附加面板，保持原版 UI 结构与样式。
(() => {
  "use strict";
  if (window.__bp_inject) return;
  window.__bp_inject = true;

  // ---------------- 服务端域名运行时改写（对原版 bundle 零侵入） ----------------
  // 原版客户端把认证/数据/生成 API 都建在 api.blueprint.io 与 *.supabase.co 上；
  // 这里在 fetch/XHR 层统一改写到本地服务端，使 /auth/v1、/rest/v1、/storage/v1、/api 全部落到本地。
  (function rewriteHosts() {
    const HOSTS = ["dkufwkuoyesnabvxiucr.supabase.co", "api.blueprint.io", "server.blueprint.io"];
    const HOST = "127.0.0.1:9418";
    const rw = (u) => {
      if (!u) return u;
      let s = String(u);
      for (const h of HOSTS) {
        if (s.indexOf(h) < 0) continue;
        s = s
          .replace(new RegExp("^https?://" + h.replace(/\./g, "\\.")), "http://" + HOST)
          .split(h).join(HOST);
      }
      return s;
    };
    // 第三方埋点域名：fetch/XHR 直接拦截（本地化：不向任何外部统计服务发数据）
    const BLOCKED = ["googletagmanager.com", "google-analytics.com", "doubleclick.net", "posthog.com", "facebook.net", "redditstatic.com", "reddit.com", "amazon-adsystem.com", "hotjar.com", "clarity.ms", "mixpanel.com", "segment.io", "criteo.com", "snap.licdn.com", "ads.linkedin.com"];
    const isBlocked = (u) => !!u && BLOCKED.some((d) => String(u).indexOf(d) >= 0);
    const origFetch = window.fetch;
    if (typeof origFetch === "function") {
      window.fetch = function (url, opts) {
        if (isBlocked(url)) {
          return Promise.resolve(new Response(JSON.stringify({ blocked: true }), { status: 200, headers: { "Content-Type": "application/json" } }));
        }
        return origFetch.call(this, rw(url), opts);
      };
    }
    const XHR = window.XMLHttpRequest;
    if (XHR && XHR.prototype) {
      const oOpen = XHR.prototype.open;
      const oSend = XHR.prototype.send;
      XHR.prototype.open = function (method, url) {
        this.__bpBlocked = isBlocked(url);
        return oOpen.apply(this, [method, rw(url)]);
      };
      XHR.prototype.send = function () {
        if (this.__bpBlocked) {
          this.status = 200;
          this.readyState = 4;
          this.responseText = "{}";
          try { this.onreadystatechange && this.onreadystatechange(); this.onload && this.onload(); } catch {}
          return;
        }
        return oSend.apply(this, arguments);
      };
    }
  })();

  // ---------------- 文案词典（精确匹配，避免误伤数据） ----------------
  const D = {
    "Sign in": "登录",
    "Log in": "登录",
    "Login": "登录",
    "Sign up": "注册",
    "Log out": "退出登录",
    "Sign out": "退出登录",
    "Community": "社区",
    "Projects": "项目",
    "Pricing": "价格",
    "FAQ": "常见问题",
    "About": "关于",
    "About us": "关于我们",
    "Docs": "文档",
    "Community Projects": "社区项目",
    "My Projects": "我的项目",
    "New project": "新建项目",
    "Back to home": "返回首页",
    "Sign in to see your projects.": "登录后即可查看你的项目。",
    "Sign in to manage your account.": "登录后即可管理你的账号。",
    "No community projects yet. Publish yours to be the first!": "还没有社区项目，发布你的第一个吧！",
    "Blueprint turns your idea into a wiring diagram, a full parts list, and exactly where to buy every piece: real listings, real prices, ready to order. No engineering degree required. No guesswork left for you to fill in.": "蓝图工坊把你的想法变成接线图、完整零件清单与真实可购链接：真实货源、真实价格、下单即用。无需工程学位，不留任何需要你自己猜测的空白。",
    "BLUEPRINT": "蓝图工坊",
    "Blueprint": "蓝图工坊",
    "BLUEPRINT LABS": "模型配置",
    "Powered by Blueprint Labs": "由蓝图工坊驱动",
    "Make Any": "把任何想法",
    "Idea Real": "变成现实",
    "Need an Idea?": "需要灵感？",
    "Upload Image": "上传图片",
    "Draw": "手绘",
    "Lite": "快速模式",
    "See more": "查看更多",
    "Try it with your idea": "用你的想法试试",
    "Try with your idea": "用你的想法试试",
    "Get started": "开始使用",
    "Open App": "打开应用",
    "Try it with your idea": "用你的想法试试",
    "Make Any Idea Real": "把任何想法变成现实",
    "Login or Signup": "登录或注册",
    "Login or create an account to get 10 free credits a week": "登录或创建账号即可使用（本地版免验证）",
    "Continue with Google": "使用 Google 登录",
    "Continue with GitHub": "使用 GitHub 登录",
    "Email": "邮箱",
    "Password": "密码",
    "Password (min 6 characters)": "密码（至少 6 位）",
    "Please wait...": "请稍候…",
    "Continue": "继续",
    "Forgot password?": "忘记密码？",
    "Or": "或",
    "New to Blueprint?": "还没有账号？",
    "Create account": "创建账号",
    "Already have an account?": "已有账号？",
    "Sign in for more credits...": "登录后即可继续使用…",
    "Invalid password": "密码错误",
    "Incorrect password.": "密码错误",
    "Password must be at least 6 characters": "密码至少需要 6 位",
    "Please fill in all fields": "请填写所有字段",
    "Could not sign you in. Please try again.": "登录失败，请重试",
    "No credits remaining": "可用次数已用完",
    "Send": "发送",
    "Stop generating": "停止生成",
    "Stop": "停止",
    "Generating...": "生成中…",
    "PLANNING ARCHITECTURE...": "正在规划整体架构…",
    "CLARIFYING DESIGN CHOICES...": "正在明确设计方案…",
    "PRESS SPACE TO JUMP": "按空格键跳过",
    "dormant": "等待中",
    "Upgrade for better models": "升级模型配置",
    "upgrade for better models": "升级模型配置",
    "Overview": "概览",
    "Electrical": "电气",
    "Mechanical": "机械",
    "Guide": "指南",
    "Wiring": "接线图",
    "Parts": "零件",
    "BOM": "物料清单",
    "Nodes": "节点",
    "Name": "名称",
    "Type": "类型",
    "Description": "描述",
    "Quantity": "数量",
    "Qty": "数量",
    "Price": "价格",
    "Estimated Cost": "预估成本",
    "Total": "合计",
    "Materials": "材料",
    "Components": "元器件",
    "Build Steps": "组装步骤",
    "Assembly": "组装",
    "Questions": "问题",
    "Settings": "设置",
    "Account": "账号",
    "Profile": "个人资料",
    "New Project": "新建项目",
    "Create Project": "创建项目",
    "Delete": "删除",
    "Delete Project": "删除项目",
    "Edit": "编辑",
    "Share": "分享",
    "Copy Link": "复制链接",
    "Export": "导出",
    "Export ZIP": "导出 ZIP",
    "Publish": "发布",
    "Unpublish": "取消发布",
    "Starred": "已收藏",
    "stars": "星标",
    "parts": "零件",
    "published": "已发布",
    "Trending": "热门",
    "Latest": "最新",
    "Search projects": "搜索项目",
    "Search": "搜索",
    "Search parts": "搜索零件",
    "What do you want to make?": "你想做什么？",
    "Describe your idea": "描述你的想法",
    "Describe a change": "描述要修改的内容",
    "Ask about this design": "就这个设计提问",
    "Welcome back": "欢迎回来",
    "Your credits": "你的额度",
    "Free": "免费",
    "Pro": "专业版",
    "Upgrade": "升级",
    "Generating plan...": "正在生成方案…",
    "Generating electrical design...": "正在生成电气设计…",
    "Generating mechanical design...": "正在生成机械设计…",
    "Design ready": "设计完成",
    "Writing build guide...": "正在编写组装指南…",
    "Generating mechanical connections...": "正在生成机械连接…",
    "Rendering project image...": "正在渲染项目图…",
    "Editing diagram...": "正在编辑原理图…",
    "Applying changes...": "正在应用修改…",
    "Complete": "完成",
    "Searching parts...": "正在搜索零件…",
    "Plan": "方案",
    "Chat": "对话",
    "History": "历史",
    "Clear chat": "清空对话",
    "Sign in to save": "登录后保存",
    "Unsaved changes": "未保存的修改",
    "Cancel": "取消",
    "Save": "保存",
    "Discard": "放弃",
    "Confirm": "确认",
    "Terms of Service": "服务条款",
    "Privacy Policy": "隐私政策",
    "Log in to continue": "请登录后继续",
    "Back": "返回",
    "Next": "下一步",
    "Skip": "跳过",
    "Finish": "完成",
    "Username": "用户名",
    "Bio": "简介",
    "Pick your style": "选择你的风格",
    "Light": "浅色",
    "Dark": "深色",
    "WHAT WOULD YOU LIKE YOUR USERNAME TO BE?": "想给自己起什么用户名？",
    "3–20 characters · lowercase letters, numbers, underscores": "3–20 个字符 · 小写字母、数字、下划线",
    "That username is unavailable.": "该用户名不可用",
    "That username is available.": "该用户名可用",
    "WHAT ROLE BEST FITS YOU?": "你最像哪种角色？",
    "Select all that apply.": "可多选。",
    "Select your roles": "选择你的角色",
    "Engineer": "工程师",
    "Product": "产品经理",
    "Designer / Artist": "设计师 / 艺术家",
    "Founder": "创始人",
    "Student / Educator": "学生 / 教育者",
    "Researcher": "研究者",
    "Hobbyist": "爱好者",
    "Other": "其他",
    "WHAT DO YOU WANT TO USE BLUEPRINT FOR?": "你想用 Blueprint 做什么？",
    "This helps us personalize your experience.": "这有助于我们为你个性化体验。",
    "Select your use cases": "选择你的用途",
    "Learning": "学习",
    "Prototyping": "原型制作",
    "Product Design": "产品设计",
    "Part Sourcing": "零件采购",
    "Brainstorm": "头脑风暴",
    "Research": "研究",
    "Build for Fun": "动手玩乐",
    "Finish setup": "完成设置",
    "Tell people a little about yourself": "介绍一下你自己吧",
    "Home": "首页",
    "INFO": "信息",
    "MECH": "机械",
    "INSTRUCTIONS": "指南",
    "AI RENDER": "AI 渲染",
    "An AI-rendered image of your project.": "你的项目的 AI 渲染图。",
    "GENERATE IMAGE": "生成图像",
    "Image generation status is unavailable.": "图像生成状态不可用。",
    "Reconnecting.": "重新连接中。",
    "ADD TAG": "添加标签",
    "Add notes about your project...": "添加项目备注…",
    "Ask about this design...": "咨询这个设计…",
    "Ask": "咨询",
    "ASK": "咨询",
    "Edit": "编辑",
    "Image generation status is unavailable": "图像生成状态不可用",
    "Reconnecting": "重新连接中",
    "AI SUMMARY": "AI 摘要",
    "RECENT": "最近",
    "Join the Discord": "加入 Discord",
    "Share Feedback": "分享反馈",
    "MANAGE ACCOUNT": "管理账号",
    "PROFILE COLOR": "个人颜色",
    "EMAIL COMMUNICATIONS": "邮件通知",
    "Reminders & suggestions": "提醒与建议",
    "Project invitations": "项目邀请",
    "When someone invites you to collaborate on a project.": "当有人邀请你协作项目时，会显示在这里。",
    "APPEARANCE": "外观",
    "Image generation status is unavailable. Reconnecting…": "图像生成状态不可用，正在重新连接…",
    "The project changed. Refresh this plan before applying it. Refreshing uses credits and adds a new planning turn to the shared chat.": "项目已发生变化。应用前请先刷新方案。",
    "This project’s chat history changed — please re-ask.": "项目的对话历史已变化，请重新提问。",
    "Chat connection interrupted. Reconnecting…": "对话连接中断，正在重连…",
    "Chat is unavailable.": "对话暂不可用。",
    "This project has used its AI generations for today. It resets at midnight UTC.": "该项目今日的 AI 生成次数已用完，UTC 零点重置。",
    "This project now has collaborators. Send your message again to use shared chat.": "该项目已有协作者，请再次发送消息以使用共享对话。",
    "Couldn't clear the chat — please try again.": "无法清空对话，请重试。",
    "Generation failed": "生成失败",
    "Refresh": "刷新",
    "Retry": "重试",
    "Saving...": "保存中…",
    "Saved": "已保存",
    "Project saved": "项目已保存",
    "Add image": "添加图片",
    "Attach image": "上传图片",
    "Attached reference": "已上传参考图",
    "New chat": "新对话",
    "You": "你",
    "Assistant": "助手",
    "Just now": "刚刚",
    "Ask blueprint to build robots": "告诉蓝图工坊你想造什么",
    "By continuing, you agree to our Terms of Service.": "继续即表示你同意我们的服务条款。"
  };

  const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
  const Dlow = {};
  for (const k in D) Dlow[k.toLowerCase()] = D[k];

  function translateNode(node) {
    if (node.nodeType === 3) {
      const t = norm(node.nodeValue);
      if (!t) return;
      if (D[t]) node.nodeValue = node.nodeValue.replace(t, D[t]);
      else if (Dlow[t.toLowerCase()] && t.toLowerCase() === t.toLowerCase()) node.nodeValue = node.nodeValue.replace(t, Dlow[t.toLowerCase()]);
      return;
    }
    if (node.nodeType !== 1) return;
    ["placeholder", "title", "aria-label"].forEach((attr) => {
      if (node.hasAttribute(attr)) {
        const v = norm(node.getAttribute(attr));
        if (v && D[v]) node.setAttribute(attr, node.getAttribute(attr).replace(v, D[v]));
        else if (v && Dlow[v.toLowerCase()]) node.setAttribute(attr, node.getAttribute(attr).replace(v, Dlow[v.toLowerCase()]));
      }
    });
    node.childNodes.forEach(translateNode);
  }

  // ---------------- 套餐/积分收敛 ----------------
  // 套餐弹窗（MONTHLY/YEARLY 切换 + BASIC/ULTRA/ENTERPRISE + 升级按钮）整体隐藏
  function hidePricingModal() {
    const modals = [...document.querySelectorAll("div")].filter((el) => {
      const t = el.textContent || "";
      return /MONTHLY/.test(t) && /YEARLY/.test(t) && /CURRENT PLAN|升级/.test(t) && /ENTERPRISE/.test(t) && el.children.length > 5;
    });
    for (const m of modals) {
      let p = m;
      for (let i = 0; i < 4 && p && p !== document.body; i++) {
        const st = p.style || {};
        if (st.position === "fixed" && p.children.length <= 3) { p.style.display = "none"; break; }
        p = p.parentElement;
      }
      m.style.display = "none";
    }
  }
  function cleanupPricing() {
    document.querySelectorAll("a,button").forEach((el) => {
      const t = (norm(el.textContent || "")).toLowerCase();
      const href = (el.getAttribute("href") || "").toLowerCase();
      const isPricing = t === "pricing" || href.startsWith("/pricing");
      if (isPricing && el.closest("nav,header,[role=navigation]")) {
        const w = el.closest("li");
        if (w && w !== el) w.remove();
        else el.remove();
      }
    });
    // 账号页/其他页面上的“升级专业版”推广卡片（购买相关）整块隐藏
    document.querySelectorAll("main *,body *").forEach((el) => {
      if (el.children.length > 0) return;
      const t = norm(el.textContent || "");
      if (!/upgrade to (pro|专业版)|for more features/i.test(t)) return;
      let card = el;
      for (let i = 0; i < 4 && card; i++) {
        card = card.parentElement;
        if (!card) break;
        const isCard = /border|rounded|card|p-|shadow/i.test(card.className || "") && card.children.length >= 2;
        if (isCard) { card.style.display = "none"; return; }
      }
      el.closest("section")?.style ? (el.closest("section").style.display = "none") : el.remove();
    });
    // 积分/配额/计费块隐藏（用户要求去掉积分与购买体系；仅限账号页避免误伤对话内容）
    if (location.pathname.startsWith("/account")) {
      document.querySelectorAll("body *").forEach((el) => {
        if (el.children.length > 0) return;
        const t = norm(el.textContent || "");
        if (t.length > 40) return;
        const hit = /manage billing|weekly credits|credits left|^credits$|^monthly$|^yearly$|^savings?$|design credits per week|save \d+%|buy credits|wallet credits|plan access|wallet balance|^cad wallet$|add credits|cad credits/i.test(t);
        if (!hit) return;
        let card = el;
        let candidate = null;
        for (let i = 0; i < 8 && card; i++) {
          card = card.parentElement;
          if (!card || card === document.body) break;
          if (card.children.length < 2) continue;
          const ct = norm(card.textContent || "");
          if (ct.length > 2000 || !/manage billing|credits?|wallet|plan access/i.test(ct)) continue;
          candidate = card;
          // 命中了套餐/钱包整块（含套餐名/积分权益行）就直接隐藏这一块
          if (/design credits|enterprise|ultra|save \d+%|buy credits|wallet balance/i.test(ct)) break;
        }
        if (candidate) { candidate.style.display = "none"; return; }
        el.style.display = "none";
      });
      // 钱包卡残块：用户名在页面上出现多次时，隐藏重复实例所在卡片
      const unames = [];
      document.querySelectorAll("body *").forEach((el) => {
        if (el.children.length > 0) return;
        const t = norm(el.textContent || "");
        if (/^user_[a-z0-9]+$/i.test(t)) unames.push({ t, el });
      });
      const seen = new Set();
      unames.forEach(({ t, el }) => {
        if (seen.has(t)) {
          let card = el;
          for (let i = 0; i < 6 && card; i++) {
            card = card.parentElement;
            if (!card || card === document.body) break;
            if (card.children.length >= 2 && card.children.length <= 6 && norm(card.textContent || "").length < 200) { card.style.display = "none"; break; }
          }
        } else seen.add(t);
      });
      // not_found 图标残留
      document.querySelectorAll("body *").forEach((el) => {
        if (el.children.length > 0) return;
        if (norm(el.textContent || "") === "not_found") el.style.display = "none";
      });
    }
    if (location.pathname.startsWith("/pricing")) {
      location.replace("/");
    }
  }

  // ---------------- 品牌：页面标题 + 站点图标 ----------------
  // 带登录态的请求（inject 自身 fetch 需携带 sb-127-auth-token）
  async function authFetch(url, opts = {}) {
    const o = { ...opts };
    const h = { ...(opts.headers || {}) };
    if (!h.Authorization) {
      try {
        const s = JSON.parse(localStorage.getItem("sb-127-auth-token") || "null");
        if (s && s.access_token) h.Authorization = "Bearer " + s.access_token;
      } catch {}
    }
    o.headers = h;
    return fetch(url, o);
  }

  function setBrand() {
    if (document.title && !/蓝图工坊/.test(document.title)) {
      document.title = document.title.replace(/Blueprint[\s\-–—]*/gi, "蓝图工坊 ").trim() || "蓝图工坊 - AI 硬件设计";
    }
    if (!document.querySelector('link[rel~="icon"][href*="bp-icon"]')) {
      const l = document.createElement("link");
      l.rel = "icon"; l.type = "image/svg+xml"; l.href = "/assets/bp-icon.svg";
      document.head.appendChild(l);
    }
  }

  // ---------------- 首页快速模式模型菜单：显示用户实际配置的模型 ----------------
  let menuCfg = null;
  let menuCfgLoaded = false;
  async function loadMenuCfg() {
    if (menuCfgLoaded) return;
    try {
      const r = await authFetch("/api/user-provider");
      if (r.ok) { menuCfg = await r.json(); menuCfgLoaded = true; }
    } catch {}
  }
  function fixModelMenu() {
    if (!menuCfg) { loadMenuCfg(); return; }
    const layers = [...document.querySelectorAll("div.absolute.top-full")].filter((d) => /GPT-5\.6|BLUEPRINT LABS|OPENAI/i.test(d.textContent || ""));
    for (const layer of layers) {
      layer.querySelectorAll("div,span,button").forEach((el) => {
        if (el.children.length > 0) return;
        const t = norm(el.textContent || "");
        const m = { "BLUEPRINT LABS": "我的模型", "OPENAI": "备用模型" };
        if (m[t]) { el.textContent = m[t]; return; }
        if (/^GPT-5\.6 (Luna|Terra|Sol)$/.test(t)) el.textContent = "已配置模型";
      });
      const items = [...layer.querySelectorAll("button.w-full.flex")];
      const names = [menuCfg.providerName || menuCfg.provider].concat((menuCfg.backups || []).map((b) => b.providerName || b.provider));
      items.forEach((btn, i) => {
        const span = btn.querySelector("span");
        if (!span) return;
        const n = names[i] || names[names.length - 1] || "已配置模型";
        span.textContent = n + (i === 0 && menuCfg.model ? " · " + menuCfg.model : "");
      });
    }
    // 触发按钮上的当前模型名（model-picker-trigger）
    document.querySelectorAll(".model-picker-trigger span").forEach((span) => {
      if (/GPT|Max|Ultra|Luna|Terra|Sol/i.test(span.textContent || "")) span.textContent = menuCfg.model || "已配置模型";
    });
  }

  // ---------------- 对话区模型选择器全量替换（GPT-5.6/OPENAI/徽标） ----------------
  function fixChatModelMenu() {
    if (!menuCfg) { loadMenuCfg(); return; }
    const names = [menuCfg.providerName || menuCfg.provider].concat((menuCfg.backups || []).map((b) => b.providerName || b.provider));
    const m1 = names[0] ? names[0] + (menuCfg.model ? " · " + menuCfg.model : "") : "MiniMax · MiniMax-Text-01";
    const m2 = names[1] || "DeepSeek · DeepSeek-Chat";
    const m3 = names[2] || "通义千问 · qwen-plus";
    [...document.querySelectorAll("div,span,button,p")].forEach((el) => {
      const t = (el.textContent || "").trim();
      if (t.includes("OPENAI") || t === "BLUEPRINT LABS") { el.textContent = "我的模型"; return; }
      if (t === "GPT-5.6 Luna") { el.textContent = m1; return; }
      if (t === "GPT-5.6 Terra") { el.textContent = m2; return; }
      if (t === "GPT-5.6 Sol") { el.textContent = m3; return; }
      if (t === "ULTRA" || t === "Ultra") { el.textContent = "备用"; return; }
      if (t === "专业版" || t === "PRO" || t === "Pro" || t === "MAX" || t === "Max") { el.textContent = "主用"; return; }
      if (el.children.length !== 0) return;
      if (t === "专业版" || t === "PRO" || t === "Pro" || t === "MAX" || t === "Max") el.textContent = "主用";
      if (t === "ULTRA" || t === "Ultra") el.textContent = "备用";
    });
    // 触发器上的当前模型名
    document.querySelectorAll(".model-picker-trigger span").forEach((span) => {
      if (/快速模式|GPT|Max|Ultra|Luna|Terra|Sol/i.test(span.textContent || "")) span.textContent = menuCfg.model || "已配置模型";
    });
  }

  // ---------------- 右上角下载按钮接管（本地导出，不再弹会员） ----------------
  function fixDownloadButton() {
    if (!location.pathname.startsWith("/project/")) return;
    const btn = document.querySelector('button[aria-label="Download project ZIP"], [aria-label="Download project ZIP"]');
    if (!btn || btn.dataset.bpdl === "1") return;
    btn.dataset.bpdl = "1";
    btn.addEventListener("click", async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const m = location.pathname.match(/^\/project\/([0-9a-f-]+)/);
      if (!m) return;
      try {
        const r = await authFetch("/api/projects/" + m[1] + "/export", {});
        const data = await r.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = (data.projectName || "project") + ".json";
        document.body.appendChild(a);
        a.click();
        URL.revokeObjectURL(a.href);
        a.remove();
      } catch (err) { console.error("export failed", err); }
    }, true);
  }

  // ---------------- AI 渲染区：隐藏不可用状态文案 ----------------
  function hideAIRenderStatus() {
    [...document.querySelectorAll("div,p,span")].forEach((el) => {
      if (el.children.length !== 0) return;
      const t = (el.textContent || "").trim();
      if (t.includes("图像生成状态不可用") || t.includes("正在重新连接")) el.style.display = "none";
    });
  }

  // ---------------- 生成图像按钮接管（本地图像 API，不弹会员） ----------------
  function fixImageButton() {
    if (!location.pathname.startsWith("/project/")) return;
    const btns = [...document.querySelectorAll("button")].filter((b) => (b.textContent || "").trim() === "生成图像" || /^Generate (image|render)/i.test((b.textContent || "").trim()));
    for (const btn of btns) {
      if (btn.dataset.bpimg === "1") continue;
      btn.dataset.bpimg = "1";
      btn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const area = btn.closest("[class*=relative]") || btn.parentElement;
        const old = area && area.querySelector("img[data-bpimg]");
        if (old) { old.remove(); }
        const note = document.createElement("div");
        note.dataset.bpimg = "1";
        note.style.cssText = "color:#9ca3af;font-size:12px;text-align:center;padding:8px;";
        note.textContent = "图像生成中…";
        area && area.appendChild(note);
        const m = location.pathname.match(/^\/project\/([0-9a-f-]+)/);
        let prompt = "产品渲染图";
        if (m) {
          try {
            const rr = await authFetch("/api/projects/" + m[1], {});
            const d = await rr.json();
            if (d && (d.projectName || d.project_data)) {
              const pd = typeof d.project_data === "string" ? JSON.parse(d.project_data) : (d.project_data || {});
              prompt = (d.projectName || pd.projectName || "项目") + "，" + (pd.projectDescription || "");
            }
          } catch {}
        }
        try {
          const r = await authFetch("/api/ai-image", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt, projectName: m ? "" : undefined }) });
          const j = await r.json();
          if (!j.url) { note.textContent = j.error || "图像生成失败"; return; }
          note.textContent = "";
          const img = document.createElement("img");
          img.dataset.bpimg = "1";
          img.src = j.url;
          img.style.cssText = "max-width:100%;max-height:100%;object-fit:contain;border-radius:8px;";
          area && area.appendChild(img);
        } catch (err) { note.textContent = "图像生成失败：" + err.message; }
      }, true);
    }
  }

  // ---------------- 机械页：GENERATE CAD 接管混元 3D 生成 ----------------
  let cadBusy = false;
  function fixCadButton() {
    if (!location.pathname.startsWith("/project/")) return;
    const btns = [...document.querySelectorAll("button")].filter((b) => /GENERATE CAD|GENERATE 3D/i.test((b.textContent || "").trim()));
    for (const btn of btns) {
      if (btn.dataset.bp3d === "1") continue;
      btn.dataset.bp3d = "1";
      btn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (cadBusy) return;
        cadBusy = true;
        const titleEl = [...document.querySelectorAll("h1,h2,div")].find((e) => e.children.length === 0 && e.textContent && e.textContent.trim().length > 2 && e.textContent.trim().length < 60);
        const prompt = (titleEl ? titleEl.textContent.trim() : "硬件项目") + "，生成3D模型";
        const statusEl = document.createElement("div");
        statusEl.style.cssText = "position:fixed;right:1rem;bottom:1rem;z-index:99999;background:#030712;border:1px solid #1f2937;color:#f3f4f6;padding:.75rem 1rem;border-radius:.5rem;font-size:.75rem;max-width:22rem;box-shadow:0 10px 15px -3px rgba(0,0,0,.5);";
        document.body.appendChild(statusEl);
        const set = (t) => { statusEl.textContent = t; };
        try {
          set("正在提交混元 3D 任务…");
          const r = await authFetch("/api/3d/submit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt }) });
          const jr = await r.json();
          if (!jr.ok) throw new Error(jr.error || "提交失败");
          set("任务已提交（" + jr.jobId + "），混元 3D 生成中，约 1 分钟…");
          let done = false;
          for (let i = 0; i < 24 && !done; i++) {
            await new Promise((r2) => setTimeout(r2, 5000));
            const q = await authFetch("/api/3d/query", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jobId: jr.jobId }) });
            const qj = await q.json();
            if (!qj.ok) { set("查询失败：" + (qj.error || "")); done = true; break; }
            const st = qj.raw?.Status || qj.raw?.JobStatus || "";
            if (/DONE|SUCCEED|COMPLETED/i.test(st)) {
              const file = (qj.raw?.ResultFile3Ds || [])[0];
              const preview = qj.raw?.PreviewImageUrl;
              set("混元 3D 生成完成！");
              statusEl.appendChild(document.createElement("br"));
              if (file?.Url) {
                const link = document.createElement("a");
                link.href = file.Url; link.target = "_blank";
                link.style.cssText = "display:block;margin-top:.5rem;color:#60a5fa;text-decoration:underline;";
                link.textContent = "查看生成的 3D 模型（" + (file.Type || "GLB") + "）";
                statusEl.appendChild(link);
              }
              if (preview) {
                const img = document.createElement("img");
                img.src = preview; img.style.cssText = "display:block;margin-top:.5rem;max-width:100%;border-radius:.375rem;";
                statusEl.appendChild(img);
              }
              done = true;
            } else if (/FAIL|ERROR/i.test(st)) { set("混元 3D 生成失败：" + (qj.raw?.ErrorMessage || st)); done = true; }
          }
        } catch (e) {
          set("混元 3D 调用失败：" + (e.message || "").slice(0, 140));
        } finally {
          setTimeout(() => statusEl.remove(), 120000);
          cadBusy = false;
        }
      });
    }
  }

  // ---------------- 模型配置面板（账户页） ----------------
  let providers = [];
  let panelInjected = false;

  async function ensureProviders() {
    try {
      const r = await authFetch("/api/providers", { headers: { "Content-Type": "application/json" } });
      if (r.ok) providers = (await r.json()).providers || [];
    } catch {}
  }

  async function injectModelPanel() {
    const isAcct = /^\/(account|settings|profile)(\/|$)/.test(location.pathname);
    if (panelInjected || !isAcct) return;
    const mount = document.querySelector("main") || document.querySelector("[class*=container]") || document.body;
    if (!mount) return;
    panelInjected = true;
    const mk = (tag, cls, text) => {
      const el = document.createElement(tag);
      if (cls) el.className = cls;
      if (text) el.textContent = text;
      return el;
    };

    setTimeout(async () => {
      await ensureProviders();
      const card = mk("div", "");
      card.style.cssText = "margin-top:2rem;width:100%;max-width:44rem;border-radius:.5rem;border:1px solid #1f2937;background:#030712;padding:1rem;color:#f3f4f6;box-shadow:0 10px 15px -3px rgba(0,0,0,.4);font-size:.875rem;";
      card.appendChild(mk("h2", "", "模型配置（AI 生成后端）"));
      const sub = mk("p", "", "选择国内外大模型提供商并填写你的 API Key。保存后，所有 AI 生成（方案 / 接线图 / 零件 / 组装指南）将走该模型；未配置时使用内置演示生成器，本地即可跑通。");
      sub.style.cssText = "font-size:.75rem;color:#9ca3af;margin:.25rem 0 .75rem;";
      card.appendChild(sub);

      const row = (label) => {
        const w = mk("div", "");
        w.style.cssText = "display:flex;flex-direction:column;gap:.25rem;margin-bottom:.5rem;";
        const l = mk("label", "", label);
        l.style.cssText = "font-size:.75rem;color:#9ca3af;";
        w.appendChild(l);
        return w;
      };
      const inputCss = "width:100%;border-radius:.25rem;border:1px solid #374151;background:#111827;padding:.375rem .5rem;font-size:.875rem;color:#f3f4f6;";

      const provSel = document.createElement("select");
      provSel.style.cssText = inputCss;
      providers.forEach((p) => {
        const o = document.createElement("option");
        o.value = p.id;
        o.textContent = (p.group ? "[" + p.group + "] " : "") + p.name;
        provSel.appendChild(o);
      });

      const keyInp = document.createElement("input");
      keyInp.type = "password";
      keyInp.placeholder = "API Key";
      keyInp.style.cssText = inputCss;

      const baseInp = document.createElement("input");
      baseInp.type = "text";
      baseInp.placeholder = "Base URL（留空用默认）";
      baseInp.style.cssText = inputCss;

      const modelSel = document.createElement("select");
      modelSel.style.cssText = inputCss;
      const modelInp = document.createElement("input");
      modelInp.type = "text";
      modelInp.placeholder = "模型名称";
      modelInp.style.cssText = inputCss;
      modelInp.style.display = "none";

      const syncModels = () => {
        const p = providers.find((x) => x.id === provSel.value);
        modelSel.innerHTML = "";
        if (p && p.models && p.models.length) {
          (p.models || []).forEach((m) => {
            const o = document.createElement("option");
            o.value = m;
            o.textContent = m;
            modelSel.appendChild(o);
          });
          modelSel.style.display = "";
          modelInp.style.display = "none";
        } else {
          modelSel.style.display = "none";
          modelInp.style.display = "";
        }
      };
      provSel.addEventListener("change", syncModels);

      const w1 = row("提供商");
      w1.appendChild(provSel);
      const w2 = row("API Key");
      w2.appendChild(keyInp);
      const w3 = row("接口地址 Base URL");
      w3.appendChild(baseInp);
      const w4 = row("模型");
      w4.appendChild(modelSel);
      w4.appendChild(modelInp);
      card.append(w1, w2, w3, w4);

      const btnRow = mk("div", "");
      btnRow.style.cssText = "display:flex;gap:.5rem;margin-top:.75rem;align-items:center;";
      const btnCss = "border-radius:.25rem;border:1px solid #374151;padding:.375rem .75rem;font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;background:transparent;color:#d1d5db;cursor:pointer;";
      const saveBtn = mk("button", "", "保存配置");
      saveBtn.style.cssText = btnCss;
      const testBtn = mk("button", "", "测试连接");
      testBtn.style.cssText = btnCss;
      const status = mk("span", "", "");
      status.style.cssText = "font-size:.75rem;color:#9ca3af;";
      btnRow.append(saveBtn, testBtn, status);
      card.appendChild(btnRow);

      try {
        const r = await authFetch("/api/user-provider");
        if (r.ok) {
          const cfg = await r.json();
          if (cfg && cfg.provider) {
            provSel.value = cfg.provider;
            syncModels();
            if (cfg.apiKey) keyInp.value = cfg.apiKey;
            if (cfg.baseUrl) baseInp.value = cfg.baseUrl;
            const mv = cfg.model || "";
            if (modelSel.style.display !== "none" && [...modelSel.options].some((o) => o.value === mv)) modelSel.value = mv;
            else modelInp.value = mv;
            status.textContent = "已保存：" + (cfg.providerName || cfg.provider);
          }
        }
      } catch {}

      const readCfg = () => ({
        provider: provSel.value,
        apiKey: keyInp.value.trim(),
        baseUrl: baseInp.value.trim(),
        model: modelSel.style.display !== "none" ? modelSel.value : modelInp.value.trim()
      });

      saveBtn.addEventListener("click", async () => {
        status.textContent = "保存中…";
        try {
          const r = await authFetch("/api/user-provider", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(readCfg())
          });
          status.textContent = r.ok ? "已保存 ✓" : "保存失败：" + (await r.text()).slice(0, 120);
        } catch (e) {
          status.textContent = "保存失败：" + e.message;
        }
      });

      testBtn.addEventListener("click", async () => {
        status.textContent = "测试中…";
        try {
          const r = await authFetch("/api/llm/test", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(readCfg())
          });
          const j = await r.json();
          status.textContent = j.ok ? "连接成功（" + j.ms + "ms）" : "失败：" + (j.error || "未知错误");
        } catch (e) {
          status.textContent = "失败：" + e.message;
        }
      });

      // ---------- 3D 生成配置（混元 3D） ----------
      const card3d = mk("div", "");
      card3d.style.cssText = "margin-top:1rem;width:100%;max-width:44rem;border-radius:.5rem;border:1px solid #1f2937;background:#030712;padding:1rem;color:#f3f4f6;box-shadow:0 10px 15px -3px rgba(0,0,0,.4);font-size:.875rem;";
      card3d.appendChild(mk("h2", "", "3D 生成配置（腾讯混元 3D）"));
      const sub3d = mk("p", "", "填写腾讯云的 SecretId / SecretKey（开通「混元生3D」产品后可用）。保存后，机械页的 CAD 生成将调用混元 3D 从文本生成 3D 模型；未配置或失败时保持内置占位视图。");
      sub3d.style.cssText = "font-size:.75rem;color:#9ca3af;margin:.25rem 0 .75rem;";
      card3d.appendChild(sub3d);
      const idInp = document.createElement("input");
      idInp.type = "text"; idInp.placeholder = "SecretId";
      idInp.style.cssText = inputCss;
      const keyInp3d = document.createElement("input");
      keyInp3d.type = "password"; keyInp3d.placeholder = "SecretKey";
      keyInp3d.style.cssText = inputCss;
      const regInp = document.createElement("input");
      regInp.type = "text"; regInp.placeholder = "地域 Region（默认 ap-guangzhou）";
      regInp.style.cssText = inputCss;
      const w31 = row("SecretId"); w31.appendChild(idInp);
      const w32 = row("SecretKey"); w32.appendChild(keyInp3d);
      const w33 = row("Region"); w33.appendChild(regInp);
      card3d.append(w31, w32, w33);
      const btnRow3d = mk("div", "");
      btnRow3d.style.cssText = "display:flex;gap:.5rem;margin-top:.75rem;align-items:center;";
      const save3d = mk("button", "", "保存 3D 配置");
      save3d.style.cssText = btnCss;
      const status3d = mk("span", "", "");
      status3d.style.cssText = "font-size:.75rem;color:#9ca3af;";
      btnRow3d.append(save3d, status3d);
      card3d.appendChild(btnRow3d);
      try {
        const r = await authFetch("/api/3d/cfg");
        if (r.ok) {
          const c = await r.json();
          if (c.secretId) idInp.value = c.secretId;
          if (c.secretKey) keyInp3d.value = c.secretKey;
          if (c.region) regInp.value = c.region;
          if (c.secretId) status3d.textContent = "已保存（混元 3D 已配置）";
        }
      } catch {}
      save3d.addEventListener("click", async () => {
        status3d.textContent = "保存中…";
        try {
          const r = await authFetch("/api/3d/cfg", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ secretId: idInp.value.trim(), secretKey: keyInp3d.value.trim(), region: regInp.value.trim() || "ap-guangzhou" })
          });
          status3d.textContent = r.ok ? "已保存 ✓" : "保存失败：" + (await r.text()).slice(0, 120);
        } catch (e) { status3d.textContent = "保存失败：" + e.message; }
      });

      mount.prepend(card3d);
      mount.prepend(card);
    }, 2500);
  }

  // ---------------- 账号页：图像生成配置（可选，OpenAI 兼容 images API） ----------------
  let imgInjected = false;
  async function injectImagePanel() {
    const isAcct = /^\/(account|settings|profile)(\/|$)/.test(location.pathname);
    if (imgInjected || !isAcct) return;
    const mount = document.querySelector("main") || document.querySelector("[class*=container]") || document.body;
    if (!mount) return;
    imgInjected = true;
    const mk = (tag, cls, text) => {
      const el = document.createElement(tag);
      if (cls) el.className = cls;
      if (text) el.textContent = text;
      return el;
    };
    const inputCss = "width:100%;border-radius:.25rem;border:1px solid #374151;background:#111827;padding:.375rem .5rem;font-size:.875rem;color:#f3f4f6;";
    const row = (label) => {
      const w = mk("div", "");
      w.style.cssText = "display:flex;flex-direction:column;gap:.25rem;margin-bottom:.5rem;";
      const l = mk("label", "", label);
      l.style.cssText = "font-size:.75rem;color:#9ca3af;";
      w.appendChild(l);
      return w;
    };
    setTimeout(async () => {
      const card = mk("div", "");
      card.style.cssText = "margin-top:1rem;width:100%;max-width:44rem;border-radius:.5rem;border:1px solid #1f2937;background:#030712;padding:1rem;color:#f3f4f6;box-shadow:0 10px 15px -3px rgba(0,0,0,.4);font-size:.875rem;";
      card.appendChild(mk("h2", "", "图像生成配置（可选）"));
      const sub = mk("p", "", "填写 OpenAI 兼容的图像生成 API（如 jojo-image / 硅基流动 / 通义万相等），项目页「生成图像」即可真实出图；留空则隐藏生成功能。");
      sub.style.cssText = "font-size:.75rem;color:#9ca3af;margin:.25rem 0 .75rem;";
      card.appendChild(sub);
      const baseInp = document.createElement("input");
      baseInp.type = "text"; baseInp.placeholder = "Base URL（默认 https://api2.jojocode.com/v1）";
      baseInp.style.cssText = inputCss;
      const keyInp = document.createElement("input");
      keyInp.type = "password"; keyInp.placeholder = "API Key";
      keyInp.style.cssText = inputCss;
      const modelInp = document.createElement("input");
      modelInp.type = "text"; modelInp.placeholder = "模型名（默认 gpt-image-1）";
      modelInp.style.cssText = inputCss;
      const w1 = row("Base URL"); w1.appendChild(baseInp);
      const w2 = row("API Key"); w2.appendChild(keyInp);
      const w3 = row("模型名"); w3.appendChild(modelInp);
      card.append(w1, w2, w3);
      const btnRow = mk("div", "");
      btnRow.style.cssText = "display:flex;gap:.5rem;margin-top:.75rem;align-items:center;";
      const btnCss = "border-radius:.25rem;border:1px solid #374151;padding:.375rem .75rem;font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;background:transparent;color:#d1d5db;cursor:pointer;";
      const saveBtn = mk("button", "", "保存图像配置");
      saveBtn.style.cssText = btnCss;
      const status = mk("span", "", "");
      status.style.cssText = "font-size:.75rem;color:#9ca3af;";
      btnRow.append(saveBtn, status);
      card.appendChild(btnRow);
      try {
        const r = await authFetch("/api/image/cfg");
        if (r.ok) {
          const c = await r.json();
          if (c.baseUrl) baseInp.value = c.baseUrl;
          if (c.apiKey) keyInp.value = c.apiKey;
          if (c.model) modelInp.value = c.model;
          if (c.apiKey) status.textContent = "已保存（图像生成已配置）";
          else status.textContent = "未配置（图像生成暂不启用）";
        }
      } catch {}
      saveBtn.addEventListener("click", async () => {
        status.textContent = "保存中…";
        try {
          const r = await authFetch("/api/image/cfg", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ baseUrl: baseInp.value.trim(), apiKey: keyInp.value.trim(), model: modelInp.value.trim() })
          });
          status.textContent = r.ok ? "已保存 ✓" : "保存失败：" + (await r.text()).slice(0, 120);
        } catch (e) { status.textContent = "保存失败：" + e.message; }
      });
      mount.append(card);
    }, 2500);
  }

  // 生成页底部“升级 for better models”升级条：整体隐藏（购买相关，用户要求去掉）
  function cleanupUpgradeBar() {
    document.querySelectorAll("button,a,div,span,p").forEach((el) => {
      if (el.children.length > 0) return;
      const t = norm(el.textContent || "");
      if (!/upgrade for better models/i.test(t)) return;
      let card = el;
      for (let i = 0; i < 5 && card && card !== document.body; i++) {
        const ct = norm(card.textContent || "");
        if (ct.length > 60 && /upgrade for better models/i.test(ct) && card.children.length >= 1) {
          card.style.display = "none";
          return;
        }
        card = card.parentElement;
      }
      el.closest("button,a,div") ? (el.closest("button,a,div").style.display = "none") : (el.style.display = "none");
    });
  }

  // ---------------- 导航入口：模型设置（用户可自行配置 API） ----------------
  function injectModelEntry() {
    if (window.__bpEntry) return;
    const nav = document.querySelector("nav") || document.querySelector("header") || document.querySelector("[role=navigation]");
    if (!nav) return;
    const btn = document.createElement("a");
    btn.href = "/account";
    btn.textContent = "模型设置";
    btn.style.cssText = "cursor:pointer;display:inline-flex;align-items:center;gap:.25rem;font-size:.75rem;font-weight:600;color:#e5e7eb;padding:.375rem .75rem;border-radius:.375rem;text-decoration:none;";
    btn.addEventListener("click", (e) => { e.preventDefault(); location.href = "/account"; });
    nav.appendChild(btn);
    window.__bpEntry = true;
  }

  // ---------------- 观察器 ----------------
  let timer = null;
  const observer = new MutationObserver(() => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      setBrand();
      translateNode(document.body);
      hidePricingModal();
      cleanupPricing();
      fixModelMenu();
      fixChatModelMenu();
      fixCadButton();
      fixDownloadButton();
      hideAIRenderStatus();
      fixImageButton();
      injectModelEntry();
      injectModelPanel();
      injectImagePanel();
    }, 400);
  });
  observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ["placeholder", "title", "aria-label", "class"] });

  setTimeout(() => {
    setBrand();
    translateNode(document.body);
    hidePricingModal();
    cleanupPricing();
    fixModelMenu();
    fixChatModelMenu();
    fixCadButton();
    fixDownloadButton();
    hideAIRenderStatus();
    fixImageButton();
    injectModelEntry();
    injectModelPanel();
    injectImagePanel();
  }, 1500);

  setInterval(injectModelPanel, 3000);
  setInterval(injectImagePanel, 3000);
  setInterval(fixModelMenu, 2000);
  setInterval(fixChatModelMenu, 1500);
  setInterval(fixCadButton, 2000);
  setInterval(fixDownloadButton, 2000);
  setInterval(hideAIRenderStatus, 1500);
  setInterval(fixImageButton, 2000);
  setInterval(hidePricingModal, 1000);
  setInterval(injectModelEntry, 1500);
})();

/* =====================================================================
 * 智造工作台入口：3D 工坊 + 项目课（不改原版 bundle，只在 DOM 层加浮层）
 * ===================================================================== */
(function () {
  if (window.__bpStudioDock) return;
  window.__bpStudioDock = true;

  function pill(label, sub, href, accent, mark) {
    const a = document.createElement("a");
    a.href = href;
    a.style.cssText =
      "display:flex;align-items:center;gap:10px;text-decoration:none;padding:10px 14px;border-radius:12px;" +
      "background:rgba(9,12,16,.92);border:1px solid rgba(255,255,255,.14);backdrop-filter:blur(12px);" +
      "box-shadow:0 12px 34px rgba(0,0,0,.45);transition:transform .15s,border-color .15s;font-family:inherit";
    a.onmouseenter = () => { a.style.transform = "translateY(-2px)"; a.style.borderColor = accent; };
    a.onmouseleave = () => { a.style.transform = "none"; a.style.borderColor = "rgba(255,255,255,.14)"; };
    const dot = document.createElement("span");
    dot.style.cssText = "width:26px;height:26px;border-radius:8px;display:grid;place-items:center;font-size:12px;font-weight:800;color:#05110e;background:" + accent;
    dot.textContent = mark || label.slice(0, 1);
    const txt = document.createElement("span");
    txt.style.cssText = "display:flex;flex-direction:column;line-height:1.2";
    const b = document.createElement("b");
    b.style.cssText = "font-size:12.5px;color:#eef3f8;letter-spacing:.02em";
    b.textContent = label;
    const s = document.createElement("span");
    s.style.cssText = "font-size:10.5px;color:#8b95a4";
    s.textContent = sub;
    txt.appendChild(b); txt.appendChild(s);
    a.appendChild(dot); a.appendChild(txt);
    return a;
  }

  function mount() {
    if (document.getElementById("bp-studio-dock")) return;
    const dock = document.createElement("div");
    dock.id = "bp-studio-dock";
    dock.style.cssText =
      "position:fixed;right:18px;bottom:18px;z-index:2147483000;display:flex;flex-direction:column;gap:8px;align-items:flex-end";
    dock.appendChild(pill("3D 智造", "模型 → STL → 打印", "/studio#3d", "linear-gradient(145deg,#8dffe6,#33d1b0)", "◈"));
    dock.appendChild(pill("项目课", "按项目链路分步学", "/studio", "linear-gradient(145deg,#ffe3a5,#ffb454)", "课"));
    document.body.appendChild(dock);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
  setInterval(mount, 2500);

  // ---- 课程预览跳转：/project/<id>?focus=wiring 直达对应画面 ----
  const FOCUS_LABEL = {
    overview: ["概览", "Overview"],
    wiring: ["接线图", "Wiring"],
    mechanical: ["机械", "Mechanical"],
    parts: ["零件", "Parts"],
    instructions: ["指南", "Guide", "Instructions"],
    guide: ["指南", "Guide"],
    mech: ["机械", "Mechanical"],
  };
  const focus = new URLSearchParams(location.search).get("focus");
  if (!focus) return;
  const labels = FOCUS_LABEL[focus] || [focus];
  let tries = 0;
  let toasted = false;
  const timer = setInterval(() => {
    tries += 1;
    const nodes = Array.from(document.querySelectorAll("button,a,[role='tab'],div,span,li"));
    let hit = null;
    for (const label of labels) {
      const btn = nodes.find((el) => (el.tagName === "BUTTON" || el.getAttribute("role") === "tab") && el.textContent.trim() === label);
      const leaf = nodes.find((el) => el.children.length === 0 && el.textContent.trim() === label);
      const any = btn || leaf || nodes.find((el) => el.textContent.trim() === label);
      if (any) { hit = any; break; }
    }
    if (hit) {
      const target = hit.closest("button,[role='tab'],a") || hit;
      try { target.click(); } catch (e) { hit.click(); }
      if (!toasted) {
        toasted = true;
        const tip = document.createElement("div");
        tip.textContent = "已定位到「" + labels[0] + "」";
        tip.style.cssText =
          "position:fixed;left:50%;top:78px;transform:translateX(-50%);z-index:2147483000;" +
          "background:rgba(12,17,22,.94);border:1px solid rgba(69,230,196,.45);color:#dffcf5;" +
          "padding:8px 16px;border-radius:9px;font-size:12px;backdrop-filter:blur(10px)";
        document.body.appendChild(tip);
        setTimeout(() => tip.remove(), 2600);
      }
    }
    if (tries > 26) clearInterval(timer);
  }, 450);
})();

/* =====================================================================
 * 项目页对话内「模式选择」：方案 / 3D 智造 / 项目课
 * 选中后对话给出引导，并可直接带着项目与提示词打开工作台
 * ===================================================================== */
(function () {
  if (window.__bpChatMode) return;
  window.__bpChatMode = true;

  var PID = (location.pathname.match(/\/project\/([0-9a-fA-F-]{36})/) || [])[1] || "";
  var MODE_KEY = "bp.chat.mode";
  var mode = sessionStorage.getItem(MODE_KEY) || "plan";
  var guided = {};

  function mk(tag, css, text) {
    var e = document.createElement(tag);
    if (css) e.style.cssText = css;
    if (text != null) e.textContent = text;
    return e;
  }

  function findUI() {
    var ta = null;
    var all = document.querySelectorAll("textarea");
    for (var i = 0; i < all.length; i++) {
      var ph = all[i].placeholder || "";
      if (/Ask about this design|Ask a question|询问|设计/i.test(ph)) { ta = all[i]; break; }
    }
    if (!ta) return null;
    var box = ta;
    while (box && box.parentElement && !/border-t/.test(String(box.className))) box = box.parentElement;
    if (!box || box === document.body) box = ta.parentElement;
    var log = document.querySelector(".flex-1.overflow-y-auto") || document.querySelector('[class*="space-y-6"]');
    return { ta: ta, box: box, log: log };
  }

  function currentPrompt(ui) {
    return (ui.ta.value || "").trim();
  }

  function openStudio(ui, which) {
    var prompt = currentPrompt(ui);
    try {
      localStorage.setItem("bp.studio.handoff", JSON.stringify({
        projectId: PID, prompt: prompt, mode: which, ts: Date.now()
      }));
    } catch (e) {}
    location.href = "/studio?project=" + encodeURIComponent(PID) + "&mode=" + which + (which === "3d" ? "#3d" : "");
  }

  function guide(ui, text) {
    if (!ui.log) return;
    var bubble = mk("div",
      "max-width:92%;padding:9px 12px;border-radius:10px;border:1px solid rgba(255,255,255,.12);" +
      "background:rgba(255,255,255,.04);color:#c9d1d9;font-size:12.5px;line-height:1.6;margin-bottom:12px;white-space:pre-wrap",
      text);
    ui.log.appendChild(bubble);
    ui.log.scrollTop = ui.log.scrollHeight;
  }

  function renderBar(ui) {
    var old = document.getElementById("bp-chat-mode");
    if (old && old.dataset.mode === mode) return;
    if (old) old.remove();

    var bar = mk("div", "display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-bottom:8px");
    bar.id = "bp-chat-mode";
    bar.dataset.mode = mode;
    bar.appendChild(mk("span", "font-size:10px;letter-spacing:.12em;color:#7d8794", "模式"));

    var modes = [
      ["plan", "方案"],
      ["3d", "3D 智造"],
      ["course", "项目课"],
    ];
    modes.forEach(function (m) {
      var on = mode === m[0];
      var b = mk("button", null, m[1]);
      b.type = "button";
      b.style.cssText =
        "font:inherit;font-size:11px;padding:4px 10px;border-radius:999px;cursor:pointer;transition:.15s;" +
        (on
          ? "background:#f3f4f6;color:#0b0d10;border:1px solid #f3f4f6;font-weight:600"
          : "background:transparent;color:#9aa1ab;border:1px solid rgba(255,255,255,.14)");
      b.onclick = function () {
        mode = m[0];
        sessionStorage.setItem(MODE_KEY, mode);
        renderBar(ui);
        applyMode(ui, true);
      };
      bar.appendChild(b);
    });

    if (mode !== "plan") {
      var go = mk("a", null, "打开" + (mode === "3d" ? " 3D 工作台" : "项目课") + " →");
      go.href = "javascript:void(0)";
      go.style.cssText =
        "margin-left:auto;font-size:11px;color:#7ee7c7;text-decoration:none;border-bottom:1px dashed rgba(126,231,199,.5);white-space:nowrap";
      go.onclick = function () { openStudio(ui, mode); };
      bar.appendChild(go);
    }

    ui.box.insertBefore(bar, ui.box.firstChild);
  }

  function applyMode(ui, changed) {
    if (mode === "3d") {
      ui.ta.placeholder = "描述你要做成实物的设计，例：一个可 3D 打印的机械臂摆件…";
      if (changed || !guided["3d"]) {
        guided["3d"] = true;
        guide(ui, "已切到「3D 智造」。先说清要做什么实物、给谁用、大概多大；我会先把外观方案定下来并出预览，预览满意后点「打开 3D 工作台」，在那边生成 GLB/STL、导出切割名片。");
      }
    } else if (mode === "course") {
      ui.ta.placeholder = "说说这个项目要教什么，或直接问接线/装配…";
      if (changed || !guided["course"]) {
        guided["course"] = true;
        guide(ui, "已切到「项目课」。我会按这个项目的真实链路——接线 → 结构 → 零件 → 组装 → 3D 产出——拆成分步教程，每一步都能点「预览」跳到项目对应画面；做到哪一步卡住，直接在这里问。");
      }
    } else {
      ui.ta.placeholder = "> Ask about this design...";
    }
  }

  var busy = false;
  setInterval(function () {
    if (busy) return;
    var ui = findUI();
    if (!ui) return;
    busy = true;
    try {
      renderBar(ui);
      applyMode(ui, false);
    } finally { busy = false; }
  }, 1200);
})();