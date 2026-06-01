"""
Claudeの全プロジェクト会話を差分同期し、.md として保存
"""
import re
import sys
import json
import time
from pathlib import Path
from datetime import datetime
from itertools import groupby
from curl_cffi import requests

# ====== 設定 ======
KB_ROOT = Path(r"G:\マイドライブ\Knowledge-Base")
SECRET_FILE = Path(__file__).parent / "secret.txt"
STATE_FILE = Path(__file__).parent / "sync_state.json"
FETCH_DELAY = 1.0
# ==================

CHATS_DIR = KB_ROOT / "chats"

# Windows コンソールの絵文字対策
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AI_DISPLAY_NAMES = {"claude": "Claude", "chatgpt": "ChatGPT", "copilot": "Copilot"}
WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]


# ---------- 日付フォーマット ----------

def format_jp_datetime(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return f"{dt.month}/{dt.day}({WEEKDAYS_JA[dt.weekday()]}) {dt.hour:02d}:{dt.minute:02d}"
    except Exception:
        return ts


def format_jp_date(date_str: str) -> str:
    try:
        dt = datetime.fromisoformat(date_str)
        return f"{dt.month}/{dt.day}({WEEKDAYS_JA[dt.weekday()]})"
    except Exception:
        return date_str


# ---------- コードブロック折りたたみ ----------

CODE_BLOCK_RE = re.compile(
    r"^(?P<fence>```)(?P<lang>[^\n]*)\n(?P<code>.*?)\n```$",
    re.MULTILINE | re.DOTALL,
)


def wrap_code_blocks(text: str) -> str:
    def replacer(m):
        lang = (m.group("lang") or "").strip()
        code = m.group("code")
        n_lines = code.count("\n") + 1
        label = lang if lang else "code"
        return (
            "<details>\n"
            f"<summary>📋 {label} ({n_lines} lines)</summary>\n"
            "\n"
            f"```{lang}\n{code}\n```\n"
            "\n"
            "</details>"
        )
    return CODE_BLOCK_RE.sub(replacer, text)


# ---------- ファイル名 ----------

def slugify(s: str, max_len: int = 60) -> str:
    if not s:
        return "untitled"
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "", s)
    s = re.sub(r"\s+", "-", s).strip("-").lower()
    return s[:max_len] or "untitled"


# ---------- レンダリング ----------

def render_chat_block(payload: dict) -> str:
    ts = payload["timestamp"]
    url = payload["url"]
    ai = payload["ai"]
    ai_display = AI_DISPLAY_NAMES.get(ai.lower(), ai.capitalize())
    title = payload.get("title") or "Untitled"
    n = len(payload.get("messages", []))
    date_str = format_jp_datetime(ts)

    lines = [
        f"<!-- chat:{url} ts:{ts} ai:{ai} -->",
        "<details>",
        f"<summary>[{ai_display}] {title} ({n} msgs · {date_str})</summary>",
        "",
        f"*[Open]({url})*",
        "",
    ]

    messages = payload.get("messages", [])
    msgs_with_date = [(m.get("timestamp", ts)[:10], m) for m in messages]

    for date_key, group_iter in groupby(msgs_with_date, key=lambda x: x[0]):
        group = list(group_iter)
        date_label = format_jp_date(date_key)
        lines.append("<details>")
        lines.append(f"<summary>{date_label} ({len(group)} msgs)</summary>")
        lines.append("")
        for _, m in group:
            role = (m.get("role") or "unknown").capitalize()
            text = wrap_code_blocks((m.get("text") or "").strip())
            lines.append(f"#### {role}")
            lines.append("")
            lines.append(text)
            lines.append("")
        lines.append("</details>")
        lines.append("")

    lines.append("</details>")
    lines.append(f"<!-- /chat:{url} -->")
    return "\n".join(lines)


def render_project_file(project_name: str, blocks: list) -> str:
    blocks_sorted = sorted(blocks, key=lambda b: b["ts"], reverse=True)
    lines = [f"# {project_name}", ""]
    for b in blocks_sorted:
        lines.append(b["block"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------- 既存ファイルのパース ----------

CHAT_BLOCK_RE = re.compile(
    r"<!-- chat:(?P<url>\S+) ts:(?P<ts>\S+) ai:(?P<ai>\S+) -->\n"
    r".*?\n"
    r"<!-- /chat:(?P=url) -->",
    re.DOTALL,
)


def parse_existing_blocks(file_path: Path) -> list:
    if not file_path.exists():
        return []
    text = file_path.read_text(encoding="utf-8")
    blocks = []
    for m in CHAT_BLOCK_RE.finditer(text):
        blocks.append({
            "url": m.group("url"),
            "ts": m.group("ts"),
            "ai": m.group("ai"),
            "block": m.group(0),
        })
    return blocks


def upsert_chat(payload: dict) -> Path:
    project_name = payload.get("project") or "Untitled Project"
    file_path = CHATS_DIR / (slugify(project_name) + ".md")
    blocks = parse_existing_blocks(file_path)
    blocks = [b for b in blocks if b["url"] != payload["url"]]
    blocks.append({
        "url": payload["url"],
        "ts": payload["timestamp"],
        "ai": payload["ai"],
        "block": render_chat_block(payload),
    })
    file_path.write_text(render_project_file(project_name, blocks), encoding="utf-8")
    return file_path


# ---------- API / 同期 ----------

session_key = SECRET_FILE.read_text(encoding="utf-8").strip()
cookies = {"sessionKey": session_key}


def api_get(url):
    resp = requests.get(url, cookies=cookies, impersonate="chrome")
    resp.raise_for_status()
    return resp.json()


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_messages(chat_messages):
    out = []
    for msg in chat_messages:
        text_parts = [
            (c.get("text") or "").strip()
            for c in msg.get("content", [])
            if c.get("type") == "text"
        ]
        text = "\n\n".join(t for t in text_parts if t)
        if not text:
            continue
        out.append({
            "role": "user" if msg.get("sender") == "human" else "assistant",
            "text": text,
            "timestamp": msg.get("created_at"),
        })
    return out


def main():
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    org_uuid = api_get("https://claude.ai/api/organizations")[0]["uuid"]

    project_names = {}
    try:
        projects = api_get(f"https://claude.ai/api/organizations/{org_uuid}/projects")
        project_names = {p["uuid"]: p.get("name", "") for p in projects}
    except Exception:
        pass

    convs = api_get(f"https://claude.ai/api/organizations/{org_uuid}/chat_conversations")
    project_convs = [c for c in convs if c.get("project_uuid")]
    changed = [c for c in project_convs if state.get(c["uuid"]) != c.get("updated_at")]

    if not changed:
        print("変更なし")
        return

    print(f"変更あり: {len(changed)} 件")

    for i, c in enumerate(changed, 1):
        conv_uuid = c["uuid"]
        proj_uuid = c.get("project_uuid")
        project_name = (
            project_names.get(proj_uuid)
            or (c.get("project") or {}).get("name")
            or "Untitled Project"
        )

        detail = api_get(
            f"https://claude.ai/api/organizations/{org_uuid}"
            f"/chat_conversations/{conv_uuid}?tree=True&rendering_mode=messages"
        )
        messages = extract_messages(detail.get("chat_messages", []))
        title = detail.get("name") or "Untitled"

        if len(messages) < 2:
            print(f"[{i}/{len(changed)}] スキップ(msgs={len(messages)}): {title}")
            state[conv_uuid] = c.get("updated_at")
            time.sleep(FETCH_DELAY)
            continue

        payload = {
            "ai": "claude",
            "project": project_name,
            "title": title,
            "url": f"https://claude.ai/chat/{conv_uuid}",
            "timestamp": detail.get("updated_at"),
            "messages": messages,
        }

        try:
            upsert_chat(payload)
            state[conv_uuid] = c.get("updated_at")
            print(f"[{i}/{len(changed)}] ✅ [{project_name}] {title} ({len(messages)} msgs)")
        except Exception as e:
            print(f"[{i}/{len(changed)}] ❌ {title}: {e}")

        time.sleep(FETCH_DELAY)

    save_state(state)
    print("完了")


if __name__ == "__main__":
    main()