"""組織UUIDを取得し、会話一覧を取ってみる。"""
from pathlib import Path
from curl_cffi import requests

SECRET_FILE = Path(__file__).parent / "secret.txt"
session_key = SECRET_FILE.read_text(encoding="utf-8").strip()
cookies = {"sessionKey": session_key}


def api_get(url):
    resp = requests.get(url, cookies=cookies, impersonate="chrome")
    resp.raise_for_status()
    return resp.json()


# 1. 組織一覧
orgs = api_get("https://claude.ai/api/organizations")
print(f"組織数: {len(orgs)}")
for o in orgs:
    print(f"  - {o.get('name')}  uuid={o.get('uuid', '')[:8]}...")

# とりあえず最初の組織を使う
org_uuid = orgs[0]["uuid"]

# 2. 会話一覧
convs = api_get(f"https://claude.ai/api/organizations/{org_uuid}/chat_conversations")
print(f"\n会話総数: {len(convs)}")

# プロジェクトに属する会話だけ数える
in_project = [c for c in convs if c.get("project_uuid")]
print(f"プロジェクト内の会話: {len(in_project)}")

# 1件目の構造(キー名だけ)を確認
if convs:
    print("\n会話オブジェクトのキー一覧:")
    print(list(convs[0].keys()))