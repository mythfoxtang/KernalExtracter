# Page Answer Agent

当前版本已经改成双视图结构：

1. 抓取页面后立即创建一个 `session_id`
2. 后台同时启动两个独立 run
3. `direct` 只生成最简中文答案
4. `detail` 生成中文详细过程与答案，并保持流式输出
5. 手机端可以在两个页面之间切换

## 页面

- `GET /mobile/latest`
  打开最近一次任务的最简答案页
- `GET /mobile/session/<session_id>/direct`
  最简答案页
- `GET /mobile/session/<session_id>/detail`
  过程与答案页

## API

- `POST /api/page-capture`

返回示例：

```json
{
  "ok": true,
  "sessionId": "20260422-101530-ab12",
  "directRunId": "20260422-101531-cd34",
  "detailRunId": "20260422-101531-ef56",
  "status": "queued",
  "mobileUrl": "/mobile/session/20260422-101530-ab12/direct",
  "directMobileUrl": "/mobile/session/20260422-101530-ab12/direct",
  "detailMobileUrl": "/mobile/session/20260422-101530-ab12/detail",
  "apiUrl": "/api/sessions/20260422-101530-ab12"
}
```

- `GET /api/sessions/<session_id>`
  返回 session 信息以及 `direct` / `detail` 两个 run 的最新状态
- `GET /api/runs/<run_id>`
  返回单个 run 的状态

## 输出策略

- `direct`
  中文，极短，优先只给最终答案
- `detail`
  中文，先给答案，再给简洁步骤，手机端流式查看

## 运行输出

- `captured_pages/latest-page-capture.json`
- `agent_runs/<run_id>.json`
- `agent_runs/sessions/<session_id>.json`
- `agent_runs/sessions/latest.json`
- `agent_logs/latest-direct.json`
- `agent_logs/latest-detail.json`

## 启动

```bat
cd page-answer-agent
start-page-answer-agent.bat https://example.com/problem
```

启动后：

1. 在独立 Chrome 调试窗口打开题目页
2. 按 `Ctrl+Shift+Y`
3. 控制台会打印 `direct` 和 `detail` 两个手机页面地址

## 环境变量

```env
DASHSCOPE_API_KEY=...
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_VISION_MODEL=qwen2.5-vl-3b-instruct
QWEN_TEXT_MODEL=qwen-plus
PAGE_TASK_AGENT_TIMEOUT_SECONDS=180

PAGE_CAPTURE_HOST=0.0.0.0
PAGE_CAPTURE_PORT=8010
PAGE_MOBILE_PUBLIC_URL=http://<your-lan-ip>:8010
PAGE_MOBILE_TITLE=页面答题结果

NTFY_ENABLED=1
NTFY_SERVER=https://ntfy.sh
NTFY_TOPIC=mystery-answer-2026
```

## 安全

- 不要提交 `.env.local`
- 不要默认提交 `captured_pages/`
- 不要默认提交 `agent_logs/`
- 不要默认提交 `agent_runs/`
