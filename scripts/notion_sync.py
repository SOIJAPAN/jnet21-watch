#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新着案件を Notion「投稿管理」データベースへ自動追加する。
- 対象: data/archive.json のうち first_seen が本日(JST)の案件
- 二重登録防止: data/notion_pushed.json に登録済みIDを記録
- NOTION_TOKEN 未設定・API失敗時もパイプライン全体は止めない（exit 0）
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_news import find_deadline_line, parse_dates_in_line  # noqa: E402

JST = timezone(timedelta(hours=9))
BASE_DIR = Path(__file__).resolve().parent.parent
ARCHIVE_PATH = BASE_DIR / "data" / "archive.json"
PUSHED_PATH = BASE_DIR / "data" / "notion_pushed.json"

NOTION_DATABASE_ID = "5c92d31936a54734b095a464703a1478"  # 投稿管理
NOTION_API = "https://api.notion.com/v1/pages"


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def deadline_iso(desc: str) -> tuple[str, str]:
    """(締切日ISO, 期日行テキスト) を返す。締切が読めない場合はISOは空文字"""
    line = find_deadline_line(desc)
    if not line:
        return "", ""
    dates = parse_dates_in_line(line)
    if not dates:
        return "", line
    # 「開始日」のみの行は締切ではない
    if "開始" in line and not any(k in line for k in ("締切", "期限", "まで", "〆", "終了")):
        return "", line
    return dates[-1].isoformat(), line


def build_payload(it: dict, today_iso: str) -> dict:
    props = {
        "制度名": {"title": [{"text": {"content": it["title"][:190]}}]},
        "地域": {"select": {"name": it["region"]}},
        "ステータス": {"select": {"name": "新着"}},
    }
    kind = it.get("kind", "")
    if kind in ("補助金・助成金", "融資・貸付"):
        props["種別"] = {"select": {"name": kind}}
    dl_iso, dl_line = deadline_iso(it.get("description", ""))
    if dl_iso:
        props["締切日"] = {"date": {"start": dl_iso}}
    memo = f"{today_iso} 自動追加。"
    if dl_line:
        memo += f" {dl_line}"
    props["メモ"] = {"rich_text": [{"text": {"content": memo[:1900]}}]}
    src = it.get("source_url") or ""
    if src.startswith("http"):
        props["出典URL"] = {"url": src}
    return {"parent": {"database_id": NOTION_DATABASE_ID}, "properties": props}


def post_page(token: str, payload: dict) -> tuple[bool, str]:
    req = urllib.request.Request(
        NOTION_API,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            res.read()
        return True, ""
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as e:
        return False, str(e)


def main():
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        print("NOTION_TOKEN 未設定のため、Notion同期をスキップします")
        return

    today = datetime.now(JST).strftime("%Y-%m-%d")
    archive = load_json(ARCHIVE_PATH, {})
    pushed = load_json(PUSHED_PATH, [])

    targets = [
        it for it in archive.values()
        if it.get("first_seen") == today and it["id"] not in pushed
    ]
    if not targets:
        print("Notionへ追加する新着はありません")
        return

    ok_count = 0
    for it in targets:
        ok, err = post_page(token, build_payload(it, today))
        if ok:
            pushed.append(it["id"])
            ok_count += 1
            print(f"  + Notion登録: {it['title'][:40]}")
        else:
            print(f"  ! Notion登録失敗 ({it['title'][:30]}): {err}", file=sys.stderr)

    PUSHED_PATH.write_text(json.dumps(pushed, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Notion同期完了: {ok_count}/{len(targets)} 件")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Notion同期の失敗でページ更新全体を止めない
        print(f"Notion同期で予期しないエラー: {e}", file=sys.stderr)
