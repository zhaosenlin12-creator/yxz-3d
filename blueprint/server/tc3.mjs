// tc3.mjs — 腾讯云 TC3-HMAC-SHA256 签名（完全按官方签名方法 v3）+ 混元 3D 提交/查询
import { createHmac, createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { writeFileSync, rmSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HOST = "ai3d.tencentcloudapi.com";
const SERVICE = "ai3d";
const VERSION = "2025-05-13";
const __dir = dirname(fileURLToPath(import.meta.url));

function sha256Hex(s) { return createHash("sha256").update(s, "utf8").digest("hex"); }
function hmac(key, s) { return createHmac("sha256", key).update(s, "utf8").digest(); }

/** 按官方文档签名方法 v3 生成 Authorization */
export function tc3Sign({ secretId, secretKey, action, region = "ap-guangzhou", payload = {} }) {
  const timestamp = Math.floor(Date.now() / 1000);
  const date = new Date(timestamp * 1000).toISOString().slice(0, 10); // UTC 日期 YYYY-MM-DD
  const body = JSON.stringify(payload || {});
  const ct = "application/json; charset=utf-8";
  // 官方示例：canonical_headers 含 content-type、host、x-tc-action；SignedHeaders 对应
  const canonicalHeaders = `content-type:${ct}\nhost:${HOST}\nx-tc-action:${action.toLowerCase()}\n`;
  const signedHeaders = "content-type;host;x-tc-action";
  const canonicalRequest = `POST\n/\n\n${canonicalHeaders}\n${signedHeaders}\n${sha256Hex(body)}`;
  const hashedCanonicalRequest = sha256Hex(canonicalRequest);
  const credentialScope = `${date}/${SERVICE}/tc3_request`;
  const stringToSign = `TC3-HMAC-SHA256\n${timestamp}\n${credentialScope}\n${hashedCanonicalRequest}`;
  const secretDate = hmac("TC3" + secretKey, date);
  const secretService = hmac(secretDate, SERVICE);
  const secretSigning = hmac(secretService, "tc3_request");
  const signature = hmac(secretSigning, stringToSign).toString("hex");
  const authorization = `TC3-HMAC-SHA256 Credential=${secretId}/${credentialScope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;
  return { host: HOST, headers: { "Content-Type": ct, Host: HOST, "X-TC-Action": action, "X-TC-Version": VERSION, "X-TC-Timestamp": String(timestamp), "X-TC-Region": region }, body, authorization };
}

/** 用 curl.exe 发送（完全控制 HTTP 头，避免 fetch 规范化与签名不一致） */
export async function tc3Call({ secretId, secretKey, action, region, payload, timeout = 60000 }) {
  const req = tc3Sign({ secretId, secretKey, action, region, payload });
  const bodyFile = join(__dir, "data", "_tc3_body.json");
  writeFileSync(bodyFile, req.body, "utf8");
  const args = ["-s", "-X", "POST", `https://${req.host}/`, "-H", `Authorization: ${req.authorization}`, "-H", `Content-Type: ${req.headers["Content-Type"]}`, "-H", `X-TC-Action: ${req.headers["X-TC-Action"]}`, "-H", `X-TC-Version: ${req.headers["X-TC-Version"]}`, "-H", `X-TC-Timestamp: ${req.headers["X-TC-Timestamp"]}`, "-H", `X-TC-Region: ${req.headers["X-TC-Region"]}`, "--data-binary", `@${bodyFile}`];
  const out = await new Promise((resolve, reject) => {
    const p = spawn("C:\\Windows\\System32\\curl.exe", args, { stdio: ["ignore", "pipe", "pipe"] });
    let so = "", se = "";
    p.stdout.on("data", (d) => (so += d));
    p.stderr.on("data", (d) => (se += d));
    const t = setTimeout(() => { p.kill(); reject(new Error("curl 超时")); }, timeout);
    p.on("close", (code) => { clearTimeout(t); resolve({ code, out: so, err: se }); });
    p.on("error", (e) => { clearTimeout(t); reject(e); });
  });
  rmSync(bodyFile, { force: true });
  if (out.code !== 0) throw new Error("curl 失败 code=" + out.code + " " + out.err.slice(0, 200));
  let j = null;
  try { j = JSON.parse(out.out); } catch {}
  const resp = j?.Response || null;
  if (resp?.Error) throw new Error(`混元 3D 接口错误 ${resp.Error.Code}: ${resp.Error.Message}`);
  if (!resp) throw new Error("混元 3D 返回异常：" + out.out.slice(0, 200));
  return resp;
}

/** 提交文生 3D 任务，返回 { JobId, ... } */
export async function submitHunyuan3D({ secretId, secretKey, region, prompt, resultFormat = "GLB", enablePBR = false }) {
  if (!prompt || !prompt.trim()) throw new Error("3D 生成需要描述文本");
  return tc3Call({ secretId, secretKey, action: "SubmitHunyuanTo3DRapidJob", region, payload: { Prompt: prompt.trim().slice(0, 200), ResultFormat: resultFormat, EnablePBR: !!enablePBR, EnableGeometry: false } });
}

/** 查询任务，返回 Response（含 JobStatus / 模型 URL 等） */
export async function queryHunyuan3D({ secretId, secretKey, region, jobId }) {
  if (!jobId) throw new Error("缺少任务 ID");
  return tc3Call({ secretId, secretKey, action: "QueryHunyuanTo3DRapidJob", region, payload: { JobId: String(jobId) } });
}
