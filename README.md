# 神秘答题小助手

仓库现已只保留一套可运行链路：`page-answer-agent`。

这套链路负责：

1. 启动独立 Chrome 调试窗口
2. 监听 `Ctrl+Shift+Y` 热键抓取当前页面
3. 调用 Agent 生成答案
4. 写入本地日志
5. 可选推送到 `ntfy` 和手机结果页

## 唯一入口

进入目录后运行唯一启动脚本：

```bat
cd page-answer-agent
start-page-answer-agent.bat https://example.com/problem
```

## 目录说明

`page-answer-agent` 下的核心文件：

- `agent.py`：任务识别、主任务选择、答案生成
- `page_capture_server.py`：接收抓取结果、调用 Agent、记录日志、提供 `/mobile/latest`
- `page_capture_hotkey.py`：连接 Chrome 调试口并响应 `Ctrl+Shift+Y`
- `run_agent.py`：对已保存页面重新跑 Agent
- `start-page-answer-agent.bat`：唯一启动入口，负责一键启动完整链路
- `start-chrome-debug.ps1`：启动独立 Chrome 调试窗口

## 输出文件

- `page-answer-agent\captured_pages\latest-page-capture.json`
- `page-answer-agent\agent_logs\latest-agent-run.json`

## 环境变量

在 `page-answer-agent\.env.local` 中配置：

```env
DASHSCOPE_API_KEY=你的密钥
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_VISION_MODEL=qwen2.5-vl-3b-instruct
QWEN_TEXT_MODEL=qwen-plus
PAGE_TASK_AGENT_TIMEOUT_SECONDS=180
PAGE_TASK_AGENT_MODE=reference
PAGE_TASK_AGENT_NOTE=

PAGE_CAPTURE_HOST=0.0.0.0
PAGE_CAPTURE_PORT=8010
PAGE_MOBILE_PUBLIC_URL=http://你的局域网IP:8010
PAGE_MOBILE_TITLE=页面答题结果

NTFY_ENABLED=1
NTFY_SERVER=https://ntfy.sh
NTFY_TOPIC=mystery-answer-2026
```

## 使用流程

1. 运行 `start-page-answer-agent.bat`
2. 在独立 Chrome 中打开题目页
3. 按 `Ctrl+Shift+Y`
4. 查看控制台输出或打开 `/mobile/latest`
