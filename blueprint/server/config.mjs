// config.mjs — 蓝图服务的默认配置与用户配置合并
// 优先级：用户账号页保存的配置 > 环境变量 > server/config.json > 空（演示模式）
// 这样全新克隆即使没有 data/providers.json，也能通过 config.json 或环境变量直接工作。
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dir = dirname(fileURLToPath(import.meta.url));
// 项目根目录的 config.json（与 config.example.json 同级）
const CONFIG_FILE = join(__dir, "..", "config.json");

function readFileConfig() {
  if (!existsSync(CONFIG_FILE)) return {};
  try {
    return JSON.parse(readFileSync(CONFIG_FILE, "utf8")) || {};
  } catch {
    return {};
  }
}

function pick(...values) {
  for (const v of values) {
    if (v !== undefined && v !== null && String(v).trim() !== "") return String(v).trim();
  }
  return "";
}

function envLlm() {
  const provider = pick(process.env.BLUEPRINT_LLM_PROVIDER);
  const apiKey = pick(process.env.BLUEPRINT_LLM_API_KEY, process.env.DEEPSEEK_API_KEY);
  const baseUrl = pick(process.env.BLUEPRINT_LLM_BASE_URL);
  const model = pick(process.env.BLUEPRINT_LLM_MODEL);
  if (!provider && !apiKey) return null;
  return { provider: provider || "deepseek", apiKey, baseUrl, model, providerName: "环境变量配置", source: "env" };
}

export function effectiveLlm(userId, allCfgs = {}) {
  const own = allCfgs[userId];
  if (own && (own.apiKey || own.provider === "ollama" || own.baseUrl)) return own;
  const env = envLlm();
  if (env) return env;
  const file = readFileConfig().llm;
  if (file && (file.apiKey || file.provider === "ollama" || file.baseUrl)) {
    return { ...file, providerName: file.providerName || "config.json", source: "config" };
  }
  return null;
}

export function effectiveImage(userId, allCfgs = {}) {
  const own = allCfgs[userId];
  if (own && own.apiKey) return own;
  const file = readFileConfig().image;
  if (file && file.apiKey) return { ...file, source: "config" };
  return null;
}

export function effective3d(userId, allCfgs = {}) {
  const own = allCfgs[userId];
  if (own && own.secretId && own.secretKey) return own;
  const file = readFileConfig().tencent3d;
  if (file && file.secretId && file.secretKey) return { ...file, source: "config" };
  const env = {
    secretId: pick(process.env.BLUEPRINT_TENCENT_SECRET_ID),
    secretKey: pick(process.env.BLUEPRINT_TENCENT_SECRET_KEY),
    region: pick(process.env.BLUEPRINT_TENCENT_REGION) || "ap-guangzhou",
  };
  return env.secretId && env.secretKey ? { ...env, source: "env" } : null;
}

export function configSummary() {
  const f = readFileConfig();
  return {
    file: existsSync(CONFIG_FILE),
    llm: !!(envLlm() || (f.llm && (f.llm.apiKey || f.llm.provider === "ollama" || f.llm.baseUrl))),
    image: !!(f.image && f.image.apiKey),
    tencent3d: !!(f.tencent3d && f.tencent3d.secretId && f.tencent3d.secretKey),
  };
}
