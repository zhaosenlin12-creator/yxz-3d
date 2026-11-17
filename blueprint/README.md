# Blueprint 智造工作台

这是合并进「宜小智」主应用右侧对话里的 Blueprint 工作模式源码，独立也能启动。它复用宜小智的 3D/预览后端（默认 `8100`），自己提供：

- 项目蓝图工作台：`/studio`
- 3D 工坊：`/studio#3d`
- 课程模式：把项目的接线、机械、零件、组装和 3D 产出转成分步教程
- 邮箱注册/登录、项目保存、SSE 生成、模型/图像/3D 配置页

## 1. 环境要求

- Node.js **18 或以上**（使用内置 `fetch`，不需要 npm 依赖）
- 宜小智 3D 后端可选：默认 `http://127.0.0.1:8100`；不启动也能进工作台，只是 3D 预览不可用
- Windows 10/11 x64、macOS、Linux 均可运行

## 2. 配置（不要猜字段）

复制模板：

```bash
cp config.example.json config.json
```

编辑 `config.json`：

```json
{
  "llm": {
    "provider": "deepseek",
    "apiKey": "sk-...",
    "baseUrl": "https://api.deepseek.com/v1",
    "model": "deepseek-chat"
  },
  "image": {
    "baseUrl": "https://api2.jojocode.com/v1",
    "apiKey": "...",
    "model": "gpt-image-2"
  },
  "tencent3d": {
    "secretId": "...",
    "secretKey": "...",
    "region": "ap-guangzhou"
  }
}
```

配置优先级（从高到低）：

1. 用户在「账号 / 模型设置」页保存到 `server/data/providers.json`、`imgcfgs.json`、`3dcfgs.json` 的配置
2. 环境变量：
   - `BLUEPRINT_LLM_PROVIDER` / `BLUEPRINT_LLM_API_KEY` / `BLUEPRINT_LLM_BASE_URL` / `BLUEPRINT_LLM_MODEL`
   - `BLUEPRINT_IMAGE_BASE_URL` / `BLUEPRINT_IMAGE_API_KEY` / `BLUEPRINT_IMAGE_MODEL`
   - `BLUEPRINT_TENCENT_SECRET_ID` / `BLUEPRINT_TENCENT_SECRET_KEY` / `BLUEPRINT_TENCENT_REGION`
3. `config.json`
4. 全空：走内置确定性演示模板，项目/课程仍可完整跑通，只是不用大模型

`config.json` 和 `server/data/*.json` 已在 `.gitignore` 中，禁止提交真实密钥和用户数据。

## 3. 启动

```bash
node server/server.mjs
# 或
npm start
```

默认端口：

- `BLUEPRINT_PORT` / `PORT` → `9418`
- `YXZ_PORT` → `8100`

例：测试时换端口

```bash
BLUEPRINT_PORT=9420 YXZ_PORT=8100 node server/server.mjs
```

启动后打开：

- 工作台：`http://127.0.0.1:9418/studio`
- 3D 工坊：`http://127.0.0.1:9418/studio#3d`
- 蓝图首页：`http://127.0.0.1:9418/`

## 4. 首次使用

1. 打开 `/studio`，右上角「登录 / 注册」。
2. 用任意邮箱注册（密码至少 6 位），本地直接登录，不发验证邮件。
3. 在「模型设置」里填 LLM（也可用 `config.json` / 环境变量预置）。
4. 新建项目，输入需求，工作台会生成蓝图；点「生成 3D」会走 `/yxz/api/3d_cartoon` 到宜小智 3D 后端。
5. 在右侧「课程」里选择学段，生成课程；每一步的 `preview.url` 会跳到 `/project/<id>?tab=...` 或 `/studio#3d`。

## 5. 配置与链路自检

```bash
curl http://127.0.0.1:9418/api/config-status
curl http://127.0.0.1:9418/api/studio/status
curl http://127.0.0.1:9418/api/providers
```

- `/api/config-status`：返回 `llm/image/tencent3d` 是否已配置（不返回密钥）。
- `/api/studio/status`：返回 `yxz.alive` 与 3D 后端健康详情。
- `/api/providers`：返回所有可选 LLM 提供商和模型名，前端设置页直接用这份数据。

## 6. 数据目录

`server/data/` 首次写入时自动创建：

| 文件 | 内容 |
|---|---|
| `users.json` | 本地注册用户（密码为 SHA-256） |
| `projects.json` | 蓝图项目 |
| `providers.json` | 每个用户的 LLM 配置 |
| `imgcfgs.json` | 每个用户的图像生成配置 |
| `3dcfgs.json` | 每个用户的腾讯混元 3D 配置 |
| `courses.json` | 课程模式下生成的教程 |

这些文件都不进 Git。迁移时只拷 `config.json` 和需要保留的 `data/*.json`。

## 7. 与宜小智合并时的入口

- 宜小智前端：`5199`
- Blueprint 工作台：`9418`
- 3D/预览后端：`8100`
- 对话里的「设计蓝图」模式产出的预览卡，点「打开创作面板」会带 `session=<id>` 进入：
  `http://127.0.0.1:9418/studio?session=<id>&mode=3d&n=4#3d`
- 工作台顶部横幅可回到同一会话继续修改。

## 8. 已知边界

- 3D 云端精度取决于 `8100` 后端可用的 Tripo/混元额度；额度为 0 时工作台仍可生成本地浮雕 STL。
- 没有配置 LLM 时走演示模板，这是有意保留的离线兜底，不是故障。
- 课程模式依赖项目里真实存在的 `nodes/wiring/mechanical/parts/instructionSteps`；项目数据越完整，课程步骤越具体。
