# 宜小智工作台 - 快速开始

## 🚀 首次启动（约 5-10 分钟）

### 1. 首次安装依赖
```
双击运行：INSTALL-FIRST-TIME.bat
```

等待安装完成（需要网络连接）

### 2. 启动项目
```
双击运行：START.bat
```

浏览器会自动打开 http://localhost:5199

---

## 🎯 日常使用

### 启动
```
双击：START.bat
```

### 停止
- 关闭命令行窗口
- 或按 Ctrl+C

---

## 📁 项目结构

```
pingdou-workstation-final/
├── START.bat                    # ⭐ 主启动入口
├── INSTALL-FIRST-TIME.bat       # 首次安装
├── airi/                        # 前端 (Vue3 + Three.js)
├── cartoon-print-studio/        # 后端 (FastAPI)
└── presets/                     # 预制模型
```

---

## 🌐 访问地址

- **前端界面**: http://localhost:5199
- **后端 API**: http://localhost:8000
- **API 文档**: http://localhost:8000/docs

---

## 📊 性能说明

- 首屏加载：6-10 秒（模型优化后）
- 启动时间：30-60 秒
- 推荐配置：8GB RAM + 独立显卡

---

## ❓ 常见问题

### Q: 启动失败？
A: 运行 `INSTALL-FIRST-TIME.bat` 重新安装依赖

### Q: 端口被占用？
A: 关闭占用 5199 或 8000 端口的程序

### Q: 3D 模型加载慢？
A: 见 `MODEL-OPTIMIZATION-GUIDE.md` 优化模型文件

---

## 📚 完整文档

- `PERFORMANCE_REPORT.md` - 性能评估报告
- `OPTIMIZATION_PLAN.md` - 优化计划
- `MODEL-OPTIMIZATION-GUIDE.md` - 模型优化指南
- `DELIVERY-CHECKLIST.md` - 交付验收清单

---

**技术栈**: Vue3 + Three.js + VRM + FastAPI + Python
**版本**: 1.0.0
**最后更新**: 2024
