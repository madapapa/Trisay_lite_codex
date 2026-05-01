# Trisay Lite

Trisay Lite 是一个面向会议场景的本地语音转录 Web 应用方案。目标是支持中文普通话和 Bahasa Indonesia，提供实时麦克风转录、上传录音文件转录、复制全文、导出 Markdown、历史记录和基础设置能力。

本方案优先使用本地模型，适配 Apple Silicon 设备：

- 前端：Vue 3 + Vite + Tailwind CSS + Pinia + Vue Router
- 后端：FastAPI + WebSocket
- 本地模型：Whisper large-v3-turbo
- Apple Silicon 推理：mlx-whisper
- 音频处理：ffmpeg
- 静音检测：Silero VAD
- 本地存储：SQLite + 本地文件目录

## 1. 技术架构图

```mermaid
flowchart LR
  User["用户浏览器<br/>Chrome / Safari"] --> Web["Vue 3 + Vite 前端"]

  Web --> UI["界面组件<br/>Dashboard / Settings / Upload / Export"]
  Web --> Audio["浏览器音频采集<br/>MediaRecorder / AudioWorklet"]
  Web --> Store["Pinia 状态管理<br/>当前会话 / 转录文本 / 设置"]

  Audio --> WS["WebSocket<br/>实时音频流"]
  UI --> API["HTTP API<br/>上传 / 历史 / 导出 / 设置"]

  WS --> Backend["FastAPI 后端"]
  API --> Backend

  Backend --> Session["会话管理<br/>Session Manager"]
  Backend --> AudioService["音频处理<br/>ffmpeg 转码 / 切片"]
  Backend --> VAD["语音活动检测<br/>Silero VAD"]
  Backend --> ASR["本地语音识别<br/>mlx-whisper"]
  ASR --> Model["Whisper large-v3-turbo<br/>Apple Silicon 本地模型"]

  Backend --> DB[("SQLite<br/>会话 / 片段 / 设置")]
  Backend --> Storage[("本地文件存储<br/>uploads / transcripts / exports")]

  Backend --> Export["导出服务<br/>Markdown .md"]
  Export --> Storage

  Backend --> Web
```

## 2. 业务系统流程图

```mermaid
flowchart TD
  Start["打开 Trisay Lite"] --> ChooseMode{"选择使用方式"}

  ChooseMode --> Live["实时会议转录"]
  ChooseMode --> Upload["上传录音文件"]

  Live --> SelectLang["选择语言<br/>Mandarin / Bahasa Indonesia"]
  SelectLang --> StartRec["点击 Start Transcription"]
  StartRec --> MicAuth{"浏览器麦克风授权"}

  MicAuth -->|允许| Capture["采集麦克风音频"]
  MicAuth -->|拒绝| MicError["提示开启麦克风权限"]

  Capture --> Chunk["按 3-5 秒切分音频"]
  Chunk --> SendWS["通过 WebSocket 发送到后端"]
  SendWS --> VadStep["检测是否有人声"]

  VadStep -->|静音| WaitMore["继续等待音频"]
  WaitMore --> Capture

  VadStep -->|有人声| Transcribe["本地 Whisper v3-turbo 转录"]
  Transcribe --> ReturnText["返回识别文本"]
  ReturnText --> ShowText["主界面追加显示文本"]
  ShowText --> Continue{"是否继续录音"}

  Continue -->|继续| Capture
  Continue -->|暂停| Pause["暂停转录"]
  Continue -->|停止| SaveSession["保存本次会话"]

  Upload --> SelectFile["选择音频文件"]
  SelectFile --> FileCheck{"文件是否有效"}

  FileCheck -->|无效| FileError["提示文件格式或大小错误"]
  FileCheck -->|有效| UploadFile["上传到后端"]

  UploadFile --> Convert["ffmpeg 转码为 16kHz mono wav"]
  Convert --> Segment["按语音段切片"]
  Segment --> BatchTranscribe["本地 Whisper v3-turbo 批量转录"]
  BatchTranscribe --> MergeText["合并完整转录文本"]
  MergeText --> ShowText

  SaveSession --> UserAction{"用户后续操作"}
  ShowText --> UserAction

  UserAction --> Copy["复制全文"]
  UserAction --> ExportMd["导出 Markdown"]
  UserAction --> NewSession["新建会话"]
  UserAction --> History["查看历史记录"]
  UserAction --> Settings["修改语言或主题"]

  Copy --> Copied["显示复制成功"]
  ExportMd --> DownloadMD["下载 .md 文件"]
  NewSession --> ChooseMode
  History --> ShowText
  Settings --> SaveSettings["保存设置到本地"]
```

## 3. 用户操作流程图

```mermaid
flowchart TD
  OpenApp["打开 Trisay Lite"] --> Home["进入 Dashboard"]
  Home --> PickLanguage["选择转录语言<br/>Mandarin / Bahasa Indonesia"]
  PickLanguage --> PickMode{"选择任务"}

  PickMode --> LiveMode["实时会议转录"]
  PickMode --> UploadMode["上传录音文件"]

  LiveMode --> StartButton["点击 Start Transcription"]
  StartButton --> Permission{"授权麦克风"}
  Permission -->|允许| LiveText["查看实时转录文本"]
  Permission -->|拒绝| PermissionHelp["查看权限提示"]

  UploadMode --> ChooseFile["选择本地音频文件"]
  ChooseFile --> Uploading["等待上传和识别"]
  Uploading --> UploadedText["查看完整转录文本"]

  LiveText --> Review["检查和阅读文本"]
  UploadedText --> Review

  Review --> NextAction{"后续操作"}
  NextAction --> CopyAll["复制全文"]
  NextAction --> ExportFile["导出 Markdown"]
  NextAction --> PauseLive["暂停 / 继续"]
  NextAction --> StopLive["停止并保存"]
  NextAction --> NewMeeting["新建会话"]
  NextAction --> OpenSettings["进入 Settings"]

  CopyAll --> CopyToast["显示复制成功"]
  ExportFile --> DownloadFile["下载 .md 文件"]
  PauseLive --> LiveText
  StopLive --> Saved["保存到历史记录"]
  NewMeeting --> PickLanguage
  OpenSettings --> ChangePrefs["修改语言 / 主题"]
  ChangePrefs --> Home
```

## 4. 转录状态流转图

```mermaid
stateDiagram-v2
  [*] --> Idle

  Idle: 空闲
  Recording: 录音中
  Paused: 已暂停
  Processing: 识别中
  Uploading: 上传中
  Completed: 已完成
  Error: 出错

  Idle --> Recording: Start Transcription
  Recording --> Processing: 收到有效语音片段
  Processing --> Recording: 返回识别文本
  Recording --> Paused: Pause
  Paused --> Recording: Resume
  Recording --> Completed: Stop
  Paused --> Completed: Stop

  Idle --> Uploading: Upload Audio
  Uploading --> Processing: 文件上传完成
  Processing --> Completed: 文件识别完成

  Recording --> Error: 麦克风 / WebSocket 错误
  Uploading --> Error: 文件无效 / 上传失败
  Processing --> Error: 模型识别失败
  Error --> Idle: Dismiss / New Session

  Completed --> Idle: New Session
  Completed --> Completed: Copy / Export / View History
```

## 5. 前后端时序图

```mermaid
sequenceDiagram
  autonumber
  actor User as 用户
  participant Web as Vue 前端
  participant API as FastAPI 后端
  participant Audio as 音频处理服务
  participant VAD as Silero VAD
  participant ASR as mlx-whisper
  participant DB as SQLite / 本地存储

  User->>Web: 选择语言并点击开始转录
  Web->>User: 请求麦克风权限
  User-->>Web: 允许麦克风
  Web->>API: 建立 WebSocket 会话
  API->>DB: 创建转录会话
  DB-->>API: 返回 session_id
  API-->>Web: 会话已建立

  loop 每 3-5 秒音频片段
    Web->>API: 发送音频 chunk
    API->>Audio: 转码 / 标准化音频
    Audio-->>API: 16kHz mono 音频
    API->>VAD: 检测是否有人声
    VAD-->>API: speech / silence
    alt 有人声
      API->>ASR: 调用 Whisper large-v3-turbo
      ASR-->>API: 返回转录文本
      API->>DB: 保存转录片段
      API-->>Web: 推送 transcript segment
      Web-->>User: 主界面追加显示文本
    else 静音
      API-->>Web: 保持连接，不追加文本
    end
  end

  User->>Web: 点击停止
  Web->>API: 关闭转录会话
  API->>DB: 保存完整 transcript
  API-->>Web: 返回完成状态

  User->>Web: 点击导出 Markdown
  Web->>API: 请求导出 .md
  API->>DB: 读取 transcript
  API->>DB: 保存导出文件记录
  API-->>Web: 返回下载文件
  Web-->>User: 下载 .md
```

## MVP 范围建议

第一版建议优先完成：

- Dashboard 主界面
- Mandarin / Bahasa Indonesia 语言切换
- 麦克风准实时转录
- 上传录音文件转录
- 暂停、停止、新建会话
- 复制全文
- 导出 Markdown
- Settings 页面保存语言和主题偏好
- SQLite 保存历史记录

暂缓功能：

- 用户账号
- 云端同步
- 多人说话人分离
- 自动摘要
- 翻译

## 6. 本地发布版启动

开发模式可以继续使用 Vite 和 FastAPI 两个服务。日常使用时可以构建前端生产文件，并让 FastAPI 直接托管页面：

```bash
cd /Users/vtl/project/codex/trisay_lite/frontend
npm run build
```

构建完成后，只需要启动后端：

```bash
cd /Users/vtl/project/codex/trisay_lite
scripts/start_trisay.sh
```

然后打开：

```text
http://127.0.0.1:8000
```

也可以用 macOS 启动器：

```bash
cp -R "macos/Trisay Lite.app" /Applications/
```

复制后可通过 Spotlight 搜索 `Trisay Lite` 启动。启动器会检查 `127.0.0.1:8000` 是否已有服务；没有运行时会启动后端，并自动打开浏览器。
