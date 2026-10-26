# 真实场景重建云端契约

浏览器将 12–80 张环绕照片，或一段环绕视频，提交为场景任务。照片不会进入 3D 打印链路。

## 应用接口

- `POST /api/scenes`：`multipart/form-data`，字段为 `title` 与重复的 `captures` 文件。
- `GET /api/scenes/{sceneId}`：返回任务状态、采集质量与真实场景资产地址。
- `POST /api/scenes/{sceneId}/submit`：向环境变量 `SCENE_TRAINER_URL` 指定的 GPU 训练器提交采集集。
- `POST /api/scenes/{sceneId}/asset`：训练器或教师回传 `.ply` / `.splat` / `.sog` 成果，自动进入 SuperSplat Viewer。

## GPU 训练器接口

`SCENE_TRAINER_URL` 接收 `multipart/form-data`：

- `manifest`：JSON，含 `sceneId`、`title`、采集文件元数据。
- `captures`：重复字段，每项是一张图片或一段视频。

初次响应必须为 JSON：`{ "remoteJobId": "...", "statusUrl": "..." }`。训练器可使用 Nerfstudio / gsplat / GraphDECO，完成后将 `.ply`、`.splat` 或 `.sog` 回传至应用的 asset 接口。没有配置训练器时，应用会停在“等待云训练器”，不会伪造真实重建结果。
