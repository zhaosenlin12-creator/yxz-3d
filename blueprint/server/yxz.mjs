// yxz.mjs - 宜小智（yxz-3d）能力服务的网关
// 前端只认 9418 一个入口：/yxz/api/* → FastAPI(默认 8100)，避免端口漂移与跨域。
import http from "node:http";

const YXZ_HOST = "127.0.0.1";
export const YXZ_PORT = Number(process.env.YXZ_PORT || 8100);

export function yxzAlive() {
  return new Promise((resolve) => {
    const req = http.request({ host: YXZ_HOST, port: YXZ_PORT, path: "/api/health", method: "GET", timeout: 3000 }, (res) => {
      let s = "";
      res.on("data", (d) => (s += d));
      res.on("end", () => {
        try { resolve({ ok: true, data: JSON.parse(s) }); } catch { resolve({ ok: true, data: null }); }
      });
    });
    req.on("timeout", () => { req.destroy(); resolve({ ok: false, error: "timeout" }); });
    req.on("error", (e) => resolve({ ok: false, error: e.message }));
    req.end();
  });
}

export function proxyYxz(req, res, url) {
  const target = url.pathname.replace(/^\/yxz/, "") + (url.search || "");
  const headers = { ...req.headers };
  delete headers.host;
  delete headers.origin;
  delete headers.referer;
  const up = http.request({ host: YXZ_HOST, port: YXZ_PORT, path: target, method: req.method, headers }, (r) => {
    res.writeHead(r.statusCode || 502, r.headers);
    r.pipe(res);
  });
  up.on("error", () => {
    if (!res.headersSent) {
      res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
    }
    res.end(JSON.stringify({ error: "yxz_unavailable", msg: "3D 能力服务未启动，请运行 start-all.ps1" }));
  });
  req.pipe(up);
}
