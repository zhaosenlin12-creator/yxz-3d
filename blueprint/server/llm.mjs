// llm.mjs - 国内外大模型提供商注册表 + 统一调用适配层
// 分类：国内（OpenAI 兼容 / 原生）、国际（OpenAI / Anthropic / Gemini）、本地（Ollama）

export const PROVIDERS = [
  // ---------- 国内 ----------
  {
    id: "volcengine",
    name: "豆包（火山方舟 Volcengine Ark）",
    group: "国内",
    kind: "openai",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    models: ["doubao-seed-1-6-250615", "doubao-pro-32k-250528", "deepseek-v3.1-250618", "deepseek-r1-250528"],
    supportsJson: true,
    note: "在火山方舟控制台创建推理接入点后可直接使用模型名，也可填写接入点 ID（endpoint）。",
  },
  {
    id: "deepseek",
    name: "DeepSeek（深度求索）",
    group: "国内",
    kind: "openai",
    baseUrl: "https://api.deepseek.com/v1",
    models: ["deepseek-chat", "deepseek-reasoner"],
    supportsJson: true,
    note: "deepseek-reasoner 为思考模型，速度较慢但质量更高。",
  },
  {
    id: "dashscope",
    name: "通义千问（阿里云 DashScope）",
    group: "国内",
    kind: "openai",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    models: ["qwen-max", "qwen-plus", "qwen-turbo", "qwen2.5-72b-instruct"],
    supportsJson: true,
  },
  {
    id: "zhipu",
    name: "智谱 GLM",
    group: "国内",
    kind: "openai",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    models: ["glm-4-plus", "glm-4-flash", "glm-4.5", "glm-4.5-air"],
    supportsJson: true,
  },
  {
    id: "moonshot",
    name: "Kimi（月之暗面 Moonshot）",
    group: "国内",
    kind: "openai",
    baseUrl: "https://api.moonshot.cn/v1",
    models: ["kimi-k2-0711-preview", "moonshot-v1-8k", "moonshot-v1-32k"],
    supportsJson: true,
  },
  {
    id: "baidu",
    name: "文心一言（百度千帆 ERNIE）",
    group: "国内",
    kind: "openai",
    baseUrl: "https://qianfan.baidubce.com/v2",
    models: ["ernie-4.0-8k", "ernie-3.5-8k", "ernie-speed-8k"],
    supportsJson: true,
  },
  {
    id: "hunyuan",
    name: "腾讯混元",
    group: "国内",
    kind: "openai",
    baseUrl: "https://api.hunyuan.cloud.tencent.com/v1",
    models: ["hunyuan-turbo", "hunyuan-pro", "hunyuan-standard"],
    supportsJson: true,
  },
  {
    id: "siliconflow",
    name: "硅基流动 SiliconFlow（聚合）",
    group: "国内",
    kind: "openai",
    baseUrl: "https://api.siliconflow.cn/v1",
    models: ["Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3", "THUDM/glm-4-9b-chat", "deepseek-ai/DeepSeek-R1"],
    supportsJson: true,
    note: "聚合平台，可调用多款国内外开源模型，按量付费。",
  },
  {
    id: "spark",
    name: "讯飞星火",
    group: "国内",
    kind: "openai",
    baseUrl: "https://spark-api-open.xf-yun.com/v1",
    models: ["4.0Ultra", "generalv3.5", "lite"],
    supportsJson: false,
  },
  {
    id: "minimax",
    name: "MiniMax（稀宇科技）",
    group: "国内",
    kind: "openai",
    baseUrl: "https://api.minimax.chat/v1",
    models: ["MiniMax-Text-01", "MiniMax-M2", "abab6.5s-chat"],
    supportsJson: false,
    note: "多模态大模型厂商，OpenAI 兼容接口。不支持强制 json_object 模式，提示词内要求 JSON 即可。",
  },
  {
    id: "custom",
    name: "自定义（OpenAI 兼容接口）",
    group: "国内",
    kind: "openai",
    baseUrl: "https://example.com/v1",
    models: ["自定义模型名"],
    supportsJson: false,
    note: "适用于任何提供 /chat/completions 的接口（含本地部署、内网代理等）。",
  },
  // ---------- 国际 ----------
  {
    id: "openai",
    name: "OpenAI",
    group: "国际",
    kind: "openai",
    baseUrl: "https://api.openai.com/v1",
    models: ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
    supportsJson: true,
  },
  {
    id: "anthropic",
    name: "Anthropic Claude",
    group: "国际",
    kind: "anthropic",
    baseUrl: "https://api.anthropic.com/v1",
    models: ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022", "claude-opus-4-20250514"],
    supportsJson: false,
  },
  {
    id: "gemini",
    name: "Google Gemini",
    group: "国际",
    kind: "gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta",
    models: ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"],
    supportsJson: true,
  },
  // ---------- 本地 ----------
  {
    id: "ollama",
    name: "Ollama（本地部署）",
    group: "本地",
    kind: "openai",
    baseUrl: "http://127.0.0.1:11434/v1",
    models: ["qwen2.5:7b", "qwen2.5:14b", "deepseek-r1:7b", "llama3.1:8b"],
    supportsJson: true,
    note: "本地先安装 Ollama 并 pull 对应模型，无需 API Key。",
  },
];

export function getProvider(id) {
  return PROVIDERS.find((p) => p.id === id) || null;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * 统一调用入口。返回 { text, ms }；失败抛 Error（含可读的中文错误信息）。
 */
export async function callLLM({ provider, apiKey, baseUrl, model, system, user, maxTokens = 8192, timeoutMs = 15000 }) {
  const p = getProvider(provider);
  if (!p) throw new Error("未知的模型提供商，请在设置页选择后再试。");
  const base = (baseUrl || p.baseUrl).replace(/\/+$/, "");
  const key = (apiKey || "").trim();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const started = Date.now();
  try {
    let text;
    if (p.kind === "anthropic") {
      text = await callAnthropic(base, key, model, system, user, maxTokens, ctrl.signal);
    } else if (p.kind === "gemini") {
      text = await callGemini(base, key, model, system, user, maxTokens, ctrl.signal);
    } else {
      text = await callOpenAICompatible(base, key, model, system, user, maxTokens, p.supportsJson, ctrl.signal);
    }
    if (!text || !text.trim()) throw new Error("模型返回了空内容，请更换模型或重试。");
    return { text, ms: Date.now() - started };
  } finally {
    clearTimeout(timer);
  }
}

async function callOpenAICompatible(base, key, model, system, user, maxTokens, supportsJson, signal) {
  const body = {
    model,
    messages: [
      { role: "system", content: system },
      { role: "user", content: user },
    ],
    temperature: 0.35,
    max_tokens: maxTokens,
  };
  // DeepSeek/MiniMax 等接口在 response_format=json_object 时要求提示词里
  // 明确出现 "json"；普通连通性测试（ping/OK）不能带这个参数。
  if (supportsJson && /\bjson\b/i.test(`${system}\n${user}`)) body.response_format = { type: "json_object" };
  const resp = await fetch(`${base}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(key ? { Authorization: `Bearer ${key}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok) {
    const errBody = await resp.text().catch(() => "");
    throw new Error(`接口错误 ${resp.status}: ${snippet(errBody)}`);
  }
  const data = await resp.json();
  return data?.choices?.[0]?.message?.content ?? "";
}

async function callAnthropic(base, key, model, system, user, maxTokens, signal) {
  if (!key) throw new Error("Anthropic 需要填写 API Key。");
  const resp = await fetch(`${base}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": key,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({ model, max_tokens: maxTokens, system, messages: [{ role: "user", content: user }] }),
    signal,
  });
  if (!resp.ok) {
    const errBody = await resp.text().catch(() => "");
    throw new Error(`Claude 接口错误 ${resp.status}: ${snippet(errBody)}`);
  }
  const data = await resp.json();
  return data?.content?.map((c) => c.text || "").join("") ?? "";
}

async function callGemini(base, key, model, system, user, maxTokens, signal) {
  if (!key) throw new Error("Gemini 需要填写 API Key。");
  const url = `${base}/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(key)}`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      contents: [{ parts: [{ text: `${system}\n\n${user}` }] }],
      generationConfig: {
        temperature: 0.35,
        maxOutputTokens: maxTokens,
        responseMimeType: "application/json",
      },
    }),
    signal,
  });
  if (!resp.ok) {
    const errBody = await resp.text().catch(() => "");
    throw new Error(`Gemini 接口错误 ${resp.status}: ${snippet(errBody)}`);
  }
  const data = await resp.json();
  return data?.candidates?.[0]?.content?.parts?.map((p) => p.text || "").join("") ?? "";
}

function snippet(s) {
  s = String(s || "").trim();
  try {
    const j = JSON.parse(s);
    s = j.error?.message || j.message || s;
  } catch {}
  return s.slice(0, 300);
}

/** 把模型输出中夹带的 JSON 稳健地提取出来。 */
export function extractJson(text) {
  let t = String(text).trim();
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) t = fence[1].trim();
  const start = t.indexOf("{");
  const end = t.lastIndexOf("}");
  if (start >= 0 && end > start) t = t.slice(start, end + 1);
  return JSON.parse(t);
}
