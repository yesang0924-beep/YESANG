# Relay Console · 本地 AI 网关管理台

一个轻量的 Windows 桌面工具：把散落在多个本地代理脚本里的 AI 模型上游，
收进**一个网关、一个下拉菜单**。Codex / 任意 OpenAI Responses 兼容客户端
只需指向 `http://127.0.0.1:18047/v1`，就能在模型列表里直接切换多家上游。

```
Codex / WorkBuddy / 任意 Responses 客户端
        │  base_url 固定不变
        ▼
┌─────────────────────────┐
│  go_proxy :18047        │  ← 按「模型名前缀」路由
│   go/…      → OpenCode Go   (deepseek 系)
│   local/…   → 本地反代        (gemini / claude)
│   yh/…      → 中转站          (claude / gpt / grok)
│   yhds/…    → 中转站 DeepSeek (deepseek / qwen)
└─────────────────────────┘
```

## 为什么需要它

Codex 的 provider 与 base_url 绑定，`/model` 菜单**只能换模型名，换不了上游**。
CC Switch 类工具一次也只激活一个 provider。本项目的做法：所有上游收敛到
**一个本地网关**，由网关按模型名前缀（`go/`、`yh/`…）分流，前端用
`model_catalog_json` 把多家模型并进同一个下拉菜单——**不切换配置、不重启客户端**。

## 功能

- **状态总览**：网关 / 本地反代 / 守护进程 / 出口线路，自动刷新
- **一键启动**：自动判断缺什么拉什么，修复后自动复检
- **上游连通性**：逐个实测，区分「可用 / 限流 / 失败」
- **模型池管理**：按分组增删模型、单模型 PONG 测试，改动自动备份
- **日志与用量**：网关/守护日志双 tab；按模型汇总请求与花费
- **守护进程**：30s 巡检，网关挂掉 8s 内自动拉回；崩溃有日志留痕
- **单实例**：重复启动只弹提示，不会再叠一堆窗口

## 运行环境

- Windows 10/11（自带 WebView2 运行时）
- Python 3.10+（开发运行时）；**打包后的 exe 无需 Python**

## 开发运行

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python app.py
```

## 前端（Vue 3 + Vite）

界面源码在 `frontend/`，构建产物输出到 `web/`（**不入库**，需自行构建）。

```bash
cd frontend
npm install
npm run build       # 产物 -> ../web/index.html（单文件，JS/CSS 全内联）
```

开发时 `npm run dev` 可起 Vite dev server 在浏览器里调界面；
注意 `window.pywebview.api` 只在原生窗口里注入，浏览器中接口不可用。

**为什么打成单文件**：pywebview 以 `file://` 加载页面，而 Vite 默认给
`<script type="module">` 加 `crossorigin`，在 `file://` 下会被按 CORS 拒绝导致白屏。
用 `vite-plugin-singlefile` 把资源全部内联后没有任何外部请求，从根上避开该问题。

## 打包

```bat
build.bat        :: 生成 dist\RelayConsole.exe（单文件、无控制台）
```

打包配置在 `build.spec`，两个要点：
- `datas=[('web','web')]` —— 把前端产物打进包，运行时经 `sys._MEIPASS` 读取
- `hiddenimports` 显式声明 `webview.platforms.edgechromium` / `winforms`
  —— pywebview 后端是动态导入的，不声明会导致冻结后**启动即崩且无报错**
- `excludes` 排除 PyQt/PySide/tkinter —— 走系统 WebView2，用不到，排除后体积减半

## 前置依赖

本工具是**管理外壳**，引擎为独立的 `go_proxy.py`（多上游路由网关）与
`relay-watchdog.py`（守护进程），需另行部署。路由表 `go-routes.json`、
模型目录 `wb-model-catalog.json` 的路径可在 `app.py` 顶部常量区调整。

## License

MIT
