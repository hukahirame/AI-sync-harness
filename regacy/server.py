"""
AI Chat Auto-Saver — ローカル受信サーバー(プロジェクト単位ファイル版)

各プロジェクトにつき .md ファイルを1つだけ作り、そのプロジェクト内の
すべての会話(Claude/ChatGPT混合)を時系列で並べて保存します。

ファイル例:
    AI-Knowledge-Base/chats/personal-kb-system.md
    ├ # personal-kb-system
    ├ ## 2026-05-08
    │  ├ <!-- chat:URL ts:... ai:claude -->
    │  ├ ### [Claude 14:23] AIプロジェクト機能の比較
    │  ├ ...本文...
    │  └ <!-- /chat:URL -->
    └ ## 2026-05-09
       └ ...

同じ会話URLが再送されたら、そのブロックだけ差し替えます。
プロジェクト外のチャットは保存しません(Tampermonkey側でも判定済み)。

使い方:
    1. pip install flask
    2. KB_ROOT を自分の環境に合わせて修正
    3. python server.py
"""

import re
import sys
from pathlib import Path
from itertools import groupby
from flask import Flask, request, jsonify
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ====== 設定: ドライブの場所を書く ======
KB_ROOT = Path(r"G:\マイドライブ\Knowledge-Base")
PORT = 9999
# =================================================

CHATS_DIR = KB_ROOT / "chats"
app = Flask(__name__)

CODE_BLOCK_RE = re.compile(
    r'^(?P<fence>```)(?P<lang>[^\n]*)\n(?P<code>.*?)\n```$',
    re.MULTILINE | re.DOTALL
)


# ---------- ユーティリティ ----------
WEEKDAYS_JA = ['月', '火', '水', '木', '金', '土', '日']

def format_jp_datetime(ts: str) -> str:
    """ISO timestamp → '5/18(月) 16:14' 形式"""
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return f'{dt.month}/{dt.day}({WEEKDAYS_JA[dt.weekday()]}) {dt.hour:02d}:{dt.minute:02d}'
    except Exception:
        return ts

def format_jp_date(date_str: str) -> str:
    """'YYYY-MM-DD' → '5/18(月)' 形式"""
    try:
        dt = datetime.fromisoformat(date_str)
        return f'{dt.month}/{dt.day}({WEEKDAYS_JA[dt.weekday()]})'
    except Exception:
        return date_str

def slugify(s: str, max_len: int = 60) -> str:
    """ファイル名に使える形に整形。日本語(ひらがな・カタカナ・漢字)はそのまま残す。"""
    if not s:
        return "untitled"
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', '', s)
    s = re.sub(r'\s+', '-', s).strip('-').lower()
    return s[:max_len] or "untitled"

def wrap_code_blocks(text: str) -> str:
    """メッセージ本文中のフェンス付きコードブロックを <details> で包む。"""
    def replacer(m):
        lang = (m.group('lang') or '').strip()
        code = m.group('code')
        n_lines = code.count('\n') + 1
        label = lang if lang else 'code'
        return (
            '<details>\n'
            f'<summary>📋 {label} ({n_lines} lines)</summary>\n'
            '\n'
            f'```{lang}\n{code}\n```\n'
            '\n'
            '</details>'
        )
    return CODE_BLOCK_RE.sub(replacer, text)

# ---------- レンダリング ----------

AI_DISPLAY_NAMES = {
    'claude': 'Claude',
    'chatgpt': 'ChatGPT',
    'copilot': 'Copilot',
}


def render_chat_block(payload: dict) -> str:
    ts = payload['timestamp']
    url = payload['url']
    ai = payload['ai']
    ai_display = AI_DISPLAY_NAMES.get(ai.lower(), ai.capitalize())
    title = payload.get('title') or 'Untitled'
    n = len(payload.get('messages', []))
    date_str = format_jp_datetime(ts)

    lines = [
        f'<!-- chat:{url} ts:{ts} ai:{ai} -->',
        '<details>',
        f'<summary>[{ai_display}] {title} ({n} msgs · {date_str})</summary>',
        '',
        f'*[Open]({url})*',
        '',
    ]

    # 各メッセージに日付キー(YYYY-MM-DD)を付けてグルーピング
    messages = payload.get('messages', [])
    msgs_with_date = [(m.get('timestamp', ts)[:10], m) for m in messages]

    for date_key, group_iter in groupby(msgs_with_date, key=lambda x: x[0]):
        group = list(group_iter)
        date_label = format_jp_date(date_key)
        n_in_day = len(group)

        lines.append('<details>')
        lines.append(f'<summary>{date_label} ({n_in_day} msgs)</summary>')
        lines.append('')
        for _, m in group:
            role = (m.get('role') or 'unknown').capitalize()
            text = (m.get('text') or '').strip()
            text = wrap_code_blocks(text)
            lines.append(f'#### {role}')
            lines.append('')
            lines.append(text)
            lines.append('')
        lines.append('</details>')
        lines.append('')

    lines.append('</details>')
    lines.append(f'<!-- /chat:{url} -->')
    return '\n'.join(lines)


def render_project_file(project_name: str, blocks: list) -> str:
    """スレッドを最終更新時刻の降順で並べる。"""
    blocks_sorted = sorted(blocks, key=lambda b: b['ts'], reverse=True)
    lines = [f'# {project_name}', '']
    for b in blocks_sorted:
        lines.append(b['block'])
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


# ---------- 既存ファイルのパース ----------

# <!-- chat:URL ts:ISO ai:NAME -->
# ...本文...
# <!-- /chat:URL -->
CHAT_BLOCK_RE = re.compile(
    r'<!-- chat:(?P<url>\S+) ts:(?P<ts>\S+) ai:(?P<ai>\S+) -->\n'
    r'.*?\n'
    r'<!-- /chat:(?P=url) -->',
    re.DOTALL
)


def parse_existing_blocks(file_path: Path) -> list:
    """既存ファイルから会話ブロックを抽出して dict のリストで返す。"""
    if not file_path.exists():
        return []
    text = file_path.read_text(encoding='utf-8')
    blocks = []
    for m in CHAT_BLOCK_RE.finditer(text):
        blocks.append({
            'url': m.group('url'),
            'ts': m.group('ts'),
            'ai': m.group('ai'),
            'block': m.group(0),  # マーカー込みの完全な文字列
        })
    return blocks


# ---------- メイン処理: upsert ----------

def upsert_chat(payload: dict) -> Path:
    """プロジェクトファイルに会話を追加 or 上書き。"""
    project_name = payload.get('project') or 'Untitled Project'
    file_path = CHATS_DIR / (slugify(project_name) + '.md')

    blocks = parse_existing_blocks(file_path)

    # 同じURLの古いブロックを除外
    blocks = [b for b in blocks if b['url'] != payload['url']]

    # 新しいブロックを作って追加
    blocks.append({
        'url': payload['url'],
        'ts': payload['timestamp'],
        'ai': payload['ai'],
        'block': render_chat_block(payload),
    })

    # 全体を再レンダリングして書き出し
    file_path.write_text(
        render_project_file(project_name, blocks),
        encoding='utf-8'
    )
    return file_path


# ---------- HTTP ----------

@app.route('/save', methods=['POST', 'OPTIONS'])
def save():
    if request.method == 'OPTIONS':
        return ('', 204, {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type',
        })

    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({'error': 'invalid JSON'}), 400
    if not payload.get('messages'):
        return jsonify({'error': 'no messages'}), 400

    # プロジェクト外のチャットは保存しない(設計通り)
    if not payload.get('project'):
        return (
            jsonify({'ok': True, 'skipped': 'not in project'}),
            200,
            {'Access-Control-Allow-Origin': '*'},
        )

    try:
        path = upsert_chat(payload)
        rel = path.relative_to(KB_ROOT)
        n = len(payload['messages'])
        print(f"✅ {payload['ai']:8s} → {rel}  ({n} msgs, project: {payload['project']})")
        return (
            jsonify({'ok': True, 'file': str(rel)}),
            200,
            {'Access-Control-Allow-Origin': '*'},
        )
    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'ok': True, 'kb_root': str(KB_ROOT)})


# ---------- 起動 ----------

if __name__ == '__main__':
    if not KB_ROOT.exists():
        try:
            KB_ROOT.mkdir(parents=True, exist_ok=True)
            print(f"✅ {KB_ROOT} を作成しました")
        except Exception as e:
            print(f"❌ KB_ROOT 作成失敗: {e}")
            print(f"   server.py の KB_ROOT を環境に合わせて修正してください。")
            raise SystemExit(1)

    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("  AI Chat Auto-Saver(プロジェクト単位ファイル版)")
    print(f"  保存先: {KB_ROOT}")
    print(f"  URL:    http://127.0.0.1:{PORT}/save")
    print(f"  停止:   Ctrl+C")
    print("=" * 60)
    app.run(host='127.0.0.1', port=PORT, debug=False)
