from html import escape


def render_not_found_html(title: str, message: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
</head>
<body style="font-family:Segoe UI,PingFang SC,Microsoft YaHei,sans-serif;padding:24px;">
  <h1>{escape(title)}</h1>
  <p>{escape(message)}</p>
</body>
</html>"""


def build_html_page(*, mobile_title: str, session_id: str, current_view: str, build_mobile_view_path) -> str:
    is_direct = current_view == "direct"
    heading = "最简答案" if is_direct else "过程与答案"
    helper = "适合手机快速看结论" if is_direct else "流式刷新详细过程和最终答案"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="format-detection" content="telephone=no">
  <title>{escape(mobile_title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f1e8;
      --paper: rgba(255,255,255,0.96);
      --ink: #18222b;
      --muted: #677785;
      --accent: #0f6c8f;
      --border: rgba(15, 108, 143, 0.14);
      --ok: #1f7a49;
      --warn: #a56b12;
      --error: #a33b20;
      --shadow: 0 20px 48px rgba(46, 68, 78, 0.12);
      --code-bg: #10212b;
      --code-text: #eef6fa;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(255,255,255,0.72), transparent 28%),
        linear-gradient(180deg, #efe4d1 0%, var(--bg) 45%, #f4ece2 100%);
    }}
    .wrap {{ max-width: 720px; margin: 0 auto; padding: 18px 14px 34px; }}
    .hero {{ padding: 8px 2px 10px; }}
    .eyebrow {{ color: var(--accent); font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }}
    h1 {{ margin: 8px 0 4px; font-size: 26px; line-height: 1.15; }}
    .sub {{ color: var(--muted); font-size: 14px; line-height: 1.6; }}
    .nav {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 14px; }}
    .nav-link {{
      display: block; text-align: center; text-decoration: none; color: var(--ink);
      padding: 12px 10px; border-radius: 16px; border: 1px solid var(--border);
      background: rgba(255,255,255,0.72); font-weight: 700;
    }}
    .nav-link.active {{ color: white; background: linear-gradient(180deg, #17779a, #0f6c8f); box-shadow: var(--shadow); }}
    .panel {{ margin-top: 14px; padding: 16px; border-radius: 20px; background: var(--paper); border: 1px solid var(--border); box-shadow: var(--shadow); }}
    .status {{ display: inline-block; padding: 6px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; margin-bottom: 12px; }}
    .status.queued, .status.running {{ background: rgba(165,107,18,0.12); color: var(--warn); }}
    .status.succeeded {{ background: rgba(31,122,73,0.12); color: var(--ok); }}
    .status.failed {{ background: rgba(163,59,32,0.12); color: var(--error); }}
    .meta {{ display: grid; gap: 10px; }}
    .meta-item {{ padding: 12px; border-radius: 14px; background: #fcfbf8; border: 1px solid rgba(20, 40, 50, 0.06); }}
    .label {{ font-size: 12px; color: var(--muted); margin-bottom: 6px; }}
    .value {{ font-size: 14px; line-height: 1.6; word-break: break-word; }}
    .answer-hero {{ margin-top: 14px; padding: 18px 16px; border-radius: 18px; background: linear-gradient(180deg, rgba(215,236,245,0.95), rgba(255,255,255,0.98)); border: 1px solid rgba(15,108,143,0.16); }}
    .answer-title {{ font-size: 12px; color: var(--accent); letter-spacing: .08em; text-transform: uppercase; font-weight: 700; margin-bottom: 8px; }}
    .answer-value {{ font-size: 18px; font-weight: 800; line-height: 1.6; word-break: break-word; }}
    .stream {{
      margin-top: 14px; white-space: pre-wrap; font-size: 14px; line-height: 1.75; word-break: break-word;
      padding: 14px; border-radius: 16px; background: #fffdfa; border: 1px solid rgba(31,41,55,0.08);
      max-height: 44vh; overflow-y: auto;
    }}
    .answer {{
      margin-top: 14px; padding: 16px; border-radius: 16px;
      background: linear-gradient(180deg, rgba(214,235,246,0.45), rgba(255,255,255,0.94));
      border: 1px solid rgba(15,108,143,0.14); font-size: 15px; line-height: 1.78; word-break: break-word;
    }}
    .answer h1, .answer h2, .answer h3 {{ margin: 18px 0 10px; line-height: 1.3; }}
    .answer h1 {{ font-size: 22px; }}
    .answer h2 {{ font-size: 19px; }}
    .answer h3 {{ font-size: 17px; }}
    .answer p {{ margin: 0 0 12px; }}
    .answer ul {{ margin: 0 0 14px 18px; padding: 0; }}
    .answer li {{ margin: 0 0 8px; }}
    .answer code {{ font-family: "Cascadia Code", "Consolas", monospace; background: rgba(16, 33, 43, 0.08); padding: 1px 5px; border-radius: 6px; font-size: .95em; }}
    .answer pre {{ margin: 14px 0; padding: 14px; overflow-x: auto; border-radius: 14px; background: var(--code-bg); color: var(--code-text); line-height: 1.6; }}
    .answer pre code {{ background: transparent; padding: 0; border-radius: 0; color: inherit; }}
    .actions {{ display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }}
    button, .btn {{ border: 0; border-radius: 999px; background: var(--accent); color: white; text-decoration: none; padding: 10px 14px; font-size: 14px; cursor: pointer; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="eyebrow">{escape(heading)}</div>
      <h1>{escape(mobile_title)}</h1>
      <div class="sub">Session ID: <span id="sessionId">{escape(session_id)}</span>。{escape(helper)}</div>
      <div class="nav">
        <a class="nav-link {'active' if is_direct else ''}" href="{escape(build_mobile_view_path(session_id, 'direct'))}">最简答案</a>
        <a class="nav-link {'' if is_direct else 'active'}" href="{escape(build_mobile_view_path(session_id, 'detail'))}">过程与答案</a>
      </div>
    </div>
    <div class="panel">
      <div class="status queued" id="statusBadge">queued</div>
      <div class="meta">
        <div class="meta-item"><div class="label">页面标题</div><div class="value" id="pageTitle">加载中...</div></div>
        <div class="meta-item"><div class="label">当前状态</div><div class="value" id="progressMessage">等待状态...</div></div>
        <div class="meta-item"><div class="label">最近更新时间</div><div class="value" id="updatedAt">-</div></div>
      </div>
      <div class="answer-hero">
        <div class="answer-title">{'Direct Answer' if is_direct else 'Current Answer'}</div>
        <div class="answer-value" id="answerLead">等待答案...</div>
      </div>
      <div class="stream" id="streamPanel" style="display:{'none' if is_direct else 'block'};">等待流式内容...</div>
      <div class="answer" id="answerText" style="display:{'none' if is_direct else 'block'};"><p>等待完整答案...</p></div>
      <div class="actions">
        <button type="button" id="copyBtn">复制当前内容</button>
        <a class="btn" href="/mobile/latest">打开最新任务</a>
      </div>
    </div>
  </div>
  <script>
    const sessionId = {json.dumps(session_id)};
    const currentView = {json.dumps(current_view)};
    const statusBadge = document.getElementById("statusBadge");
    const pageTitle = document.getElementById("pageTitle");
    const progressMessage = document.getElementById("progressMessage");
    const updatedAt = document.getElementById("updatedAt");
    const answerLead = document.getElementById("answerLead");
    const streamPanel = document.getElementById("streamPanel");
    const answerText = document.getElementById("answerText");
    const copyBtn = document.getElementById("copyBtn");

    const renderMarkdown = (text) => {{
      const escaped = (text || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      return escaped
        .replace(/```([\\s\\S]*?)```/g, (_, code) => `<pre><code>${{code.trim()}}</code></pre>`)
        .replace(/^### (.+)$/gm, "<h3>$1</h3>")
        .replace(/^## (.+)$/gm, "<h2>$1</h2>")
        .replace(/^# (.+)$/gm, "<h1>$1</h1>")
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>")
        .split(/\\n\\n+/)
        .map(block => {{
          if (/^<h[1-3]>/.test(block) || /^<pre>/.test(block)) return block;
          if (/^(\\- |\\* )/m.test(block)) {{
            const items = block.split(/\\n/).filter(Boolean).map(line => `<li>${{line.slice(2)}}</li>`).join("");
            return `<ul>${{items}}</ul>`;
          }}
          return `<p>${{block.replace(/\\n/g, "<br>")}}</p>`;
        }})
        .join("");
    }};

    const renderState = (snapshot) => {{
      const run = (snapshot.runs || {{}})[currentView] || {{}};
      const page = snapshot.page || run.page || {{}};
      const status = run.status || "queued";
      statusBadge.className = `status ${{status}}`;
      statusBadge.textContent = status;
      pageTitle.textContent = page.title || "Untitled page";
      progressMessage.textContent = run.progressMessage || "处理中";
      updatedAt.textContent = run.updatedAt || "-";
      answerLead.textContent = run.directAnswer || "等待答案...";
      if (currentView === "detail") {{
        streamPanel.textContent = run.streamText || "等待流式内容...";
        answerText.innerHTML = renderMarkdown(run.finalAnswer || run.error || "等待完整答案...");
      }}
      return status;
    }};

    const refresh = async () => {{
      try {{
        const response = await fetch(`/api/sessions/${{encodeURIComponent(sessionId)}}`, {{
          cache: "no-store",
          headers: {{ "Accept": "application/json" }},
        }});
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const snapshot = await response.json();
        const status = renderState(snapshot);
        if (!["succeeded", "failed"].includes(status)) window.setTimeout(refresh, 1500);
      }} catch (error) {{
        progressMessage.textContent = `状态刷新失败: ${{error.message}}`;
        window.setTimeout(refresh, 3000);
      }}
    }};

    copyBtn?.addEventListener("click", async () => {{
      const text = currentView === "direct"
        ? (answerLead?.innerText || "")
        : ((answerText?.innerText || "") || (streamPanel?.innerText || ""));
      try {{
        await navigator.clipboard.writeText(text);
        copyBtn.innerText = "已复制";
      }} catch (error) {{
        copyBtn.innerText = "复制失败";
      }}
    }});

    refresh();
  </script>
</body>
</html>"""
