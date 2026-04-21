# Page Answer Agent

独立的页面读取 + Agent 作答模块。

职责只有一条链路：

1. 读取当前浏览器页面文本
2. 识别页面里真正需要完成的题目或任务
3. 选择主任务
4. 输出答案
5. 记录抓取和答案日志

## 目录

- `agent.py`
  任务识别、主任务选择、作答的核心 Agent
- `page_capture_server.py`
  接收抓取内容，触发 Agent，并写日志
- `page_capture_hotkey.py`
  连接 Chrome 调试窗口，按热键抓当前页
- `start-chrome-debug.ps1`
  启动独立 Chrome 调试窗口
- `start-page-answer-agent.bat`
  一键启动服务、浏览器、热键
- `一键启动页面答题浏览器.bat`
  更直白的中文启动入口
- `run_agent.py`
  对已有抓取文件手动重跑 Agent

## 使用

双击：

- `一键启动页面答题浏览器.bat`

或者命令行运行：

```bat
start-page-answer-agent.bat https://example.com/problem
```

启动后：

1. 在独立 Chrome 调试窗口里打开题目页
2. 按 `Ctrl+Shift+Y`
3. 自动抓取
4. 自动作答
5. 自动记日志

## 输出

抓取内容：

- `captured_pages/latest-page-capture.json`
- `captured_pages/page-capture-时间戳.json`

答案日志：

- `agent_logs/latest-agent-run.json`
- `agent_logs/agent-run-时间戳.json`

## 配置

在当前目录放 `.env.local`：

```env
DASHSCOPE_API_KEY=...
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_VISION_MODEL=qwen2.5-vl-3b-instruct
QWEN_TEXT_MODEL=qwen-plus
PAGE_TASK_AGENT_TIMEOUT_SECONDS=180
```

## 输出风格

当前 Agent 被约束为：

- 不讲废话
- 不写模板腔
- 逻辑完整
- 必要的定义、推导、边界、复杂度或计算步骤不能省
