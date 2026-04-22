import re
from html import escape


def compact_text(value: str, max_len: int = 160) -> str:
    text = " ".join((value or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def normalize_math_text(text: str) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\$\$(.*?)\$\$", r"\1", normalized, flags=re.S)
    normalized = re.sub(r"\$(.*?)\$", r"\1", normalized, flags=re.S)
    normalized = normalized.replace("\\[", "").replace("\\]", "")
    normalized = normalized.replace("\\(", "").replace("\\)", "")

    replacements = {
        "\\neq": "!=",
        "\\leq": "<=",
        "\\geq": ">=",
        "\\le": "<=",
        "\\ge": ">=",
        "\\times": "x",
        "\\cdot": "*",
        "\\in": "in",
        "\\notin": "not in",
        "\\to": "->",
        "\\Rightarrow": "=>",
        "\\Leftarrow": "<=",
        "\\iff": "<=>",
        "\\sum": "sum",
        "\\prod": "prod",
        "\\alpha": "alpha",
        "\\beta": "beta",
        "\\gamma": "gamma",
        "\\theta": "theta",
        "\\lambda": "lambda",
        "\\mu": "mu",
        "\\sigma": "sigma",
        "\\pi": "pi",
        "\\phi": "phi",
        "\\sqrt": "sqrt",
        "\\left": "",
        "\\right": "",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def render_inline_markdown(text: str) -> str:
    rendered = escape(text)
    rendered = re.sub(r"`([^`]+)`", lambda m: f"<code>{escape(m.group(1))}</code>", rendered)
    rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
    return rendered


def render_markdown_html(text: str) -> str:
    normalized = normalize_math_text(text)
    lines = normalized.split("\n")
    html_parts: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    in_code_block = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        combined = " ".join(line.strip() for line in paragraph_lines if line.strip())
        if combined:
            html_parts.append(f"<p>{render_inline_markdown(combined)}</p>")
        paragraph_lines.clear()

    def flush_list() -> None:
        if not list_items:
            return
        html_parts.append("<ul>" + "".join(list_items) + "</ul>")
        list_items.clear()

    def flush_code() -> None:
        nonlocal code_lines
        if not code_lines:
            return
        html_parts.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
        code_lines = []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            flush_list()
            if in_code_block:
                flush_code()
                in_code_block = False
            else:
                in_code_block = True
            continue
        if in_code_block:
            code_lines.append(line)
            continue
        if not stripped:
            flush_paragraph()
            flush_list()
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            flush_paragraph()
            list_items.append(f"<li>{render_inline_markdown(stripped[2:].strip())}</li>")
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            flush_list()
            html_parts.append(f"<h3>{render_inline_markdown(stripped[4:].strip())}</h3>")
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            flush_list()
            html_parts.append(f"<h2>{render_inline_markdown(stripped[3:].strip())}</h2>")
            continue
        if stripped.startswith("# "):
            flush_paragraph()
            flush_list()
            html_parts.append(f"<h1>{render_inline_markdown(stripped[2:].strip())}</h1>")
            continue
        paragraph_lines.append(stripped)

    flush_paragraph()
    flush_list()
    if in_code_block:
        flush_code()
    return "".join(html_parts) if html_parts else "<p>暂无内容。</p>"


def extract_direct_answer(content: str) -> str:
    normalized = normalize_math_text(content)
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line or line == "---" or line.startswith("```"):
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        if line.lower().startswith("answer:") or line.startswith("答案：") or line.startswith("答案:"):
            return compact_text(line, 220)
        return compact_text(line, 220)
    return "等待答案..."
