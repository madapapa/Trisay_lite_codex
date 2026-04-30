# Trisay Lite 开发环境

本文记录当前项目的本地开发环境和常用启动命令。

## 已确认的本机环境

- Node.js: 已安装
- npm: 已安装
- Python 3.12: 已安装
- uv: 已安装
- Homebrew: 已安装
- ffmpeg: 已安装
- sqlite3: 已安装
- git: 已安装
- pnpm: 未安装，本项目暂时不需要

## 目录结构

```text
trisay_lite/
├── frontend/             # Vue 3 + Vite 前端
├── backend/              # FastAPI 后端
│   └── .venv/            # Python 虚拟环境
├── storage/              # 本地运行数据
├── models/               # 本地模型缓存或模型说明
├── README.md
├── DEV_SETUP.md
└── trisay_lite_architecture.html
```

## 为什么需要虚拟环境

后端需要安装 FastAPI、MLX、mlx-whisper、音频处理等 Python 包。它们不应该安装到全局 Python 里，否则以后多个项目之间容易互相影响。

本项目使用：

```bash
backend/.venv
```

激活方式：

```bash
cd /Users/vtl/project/codex/trisay_lite/backend
source .venv/bin/activate
```

退出虚拟环境：

```bash
deactivate
```

## 前端启动

```bash
cd /Users/vtl/project/codex/trisay_lite/frontend
npm run dev
```

默认地址：

```text
http://127.0.0.1:5173
```

前端构建检查：

```bash
cd /Users/vtl/project/codex/trisay_lite/frontend
npm run build
```

## 后端启动

```bash
cd /Users/vtl/project/codex/trisay_lite/backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

预期返回：

```json
{"status":"ok"}
```

## 后端依赖安装

如果以后重新安装依赖：

```bash
cd /Users/vtl/project/codex/trisay_lite/backend
uv pip install -r pyproject.toml --python .venv/bin/python
```

## 前端依赖安装

如果以后重新安装依赖：

```bash
cd /Users/vtl/project/codex/trisay_lite/frontend
npm install
```

## MLX / Whisper 注意事项

`mlx-whisper` 需要访问 Apple Silicon 的 Metal GPU。某些沙箱、远程、无头终端环境可能会报：

```text
No Metal device available
```

这不一定表示安装失败。请优先在你自己的 macOS Terminal 里运行后端和模型测试。

后续接入模型时，建议使用：

```text
mlx-community/whisper-large-v3-turbo
```

## 当前验证结果

- 前端依赖安装完成
- 前端 `npm run build` 已通过
- 后端虚拟环境已创建
- 后端依赖安装完成
- FastAPI `/health` 接口已验证通过
- `mlx` 可导入
- `mlx-whisper` 在 Codex 沙箱中因无 Metal 设备无法完整导入，需在本机 Terminal 中验证
