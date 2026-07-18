#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J-Net21 支援情報ウォッチ（ダッシュボード型UI）
------------------------------------------------
・J-Net21 の公式RSS（補助金・助成金・融資）を取得
・対象地域（全国／愛知県／岐阜県／静岡県／三重県）のみ抽出
・「本日の新着」を判定し、締切カウントダウン付きのダッシュボードを生成

GitHub Actions から毎日 午前2時(JST) に実行される想定。
ローカルテスト:  python scripts/fetch_news.py --file sample.xml
"""

import argparse
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from html import escape, unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

# ---------------------------------------------------------------- 設定

RSS_URL = "https://j-net21.smrj.go.jp/snavi/support/support.xml"

TARGET_REGIONS = ["全国", "愛知県", "岐阜県", "静岡県", "三重県"]

REGION_COLORS = {
    "全国":   "#17425F",
    "愛知県": "#B4452C",
    "岐阜県": "#4A6B3A",
    "静岡県": "#2E6E8E",
    "三重県": "#7A5C99",
}

URGENT_DAYS = 14      # 残りこの日数以下 → 赤
SOON_DAYS = 45        # 残りこの日数以下 → 黄
ARCHIVE_DAYS = 14     # 過去何日分をページに残すか
SEEN_KEEP_DAYS = 120  # 既読IDを保持する日数

JST = timezone(timedelta(hours=9))

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = BASE_DIR / "docs"
SEEN_PATH = DATA_DIR / "seen.json"
ARCHIVE_PATH = DATA_DIR / "archive.json"

NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
}

# ------------------------------------------------ 情報元リンクの抽出

UA = "Mozilla/5.0 (jnet21-watch; personal use)"

ANCHOR_RE = re.compile(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)

# 情報元とみなさないドメイン（J-Net21自身・SNSシェア等）
EXCLUDE_HOSTS = (
    "smrj.go.jp", "j-net21", "jnet21",
    "twitter.com", "x.com", "facebook.com", "line.me",
    "instagram.com", "youtube.com", "google.com", "hatena",
)


def extract_source_url(html_text: str, base_url: str) -> str:
    """記事ページHTMLから「詳細情報を見る」（情報元）のリンク先を抽出"""
    candidates = []
    for m in ANCHOR_RE.finditer(html_text):
        href = unescape(m.group(1)).strip()
        text = re.sub(r"<[^>]+>", "", m.group(2))
        text = re.sub(r"\s+", "", unescape(text))
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        abs_url = urljoin(base_url, href)
        if not abs_url.startswith("http"):
            continue
        if "詳細情報を見る" in text:
            return abs_url
        candidates.append((abs_url, text))
    # フォールバック：本文中の最初の外部リンク
    for abs_url, _ in candidates:
        host = urlparse(abs_url).netloc.lower()
        if host and not any(x in host for x in EXCLUDE_HOSTS):
            return abs_url
    return ""


def fetch_article_source(article_url: str) -> str:
    """J-Net21記事ページを取得して情報元URLを返す（失敗時は空文字）"""
    try:
        req = urllib.request.Request(article_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as res:
            final_url = res.geturl()
            html_text = res.read().decode("utf-8", errors="replace")
        return extract_source_url(html_text, final_url)
    except Exception as e:
        print(f"  ! 情報元リンク取得失敗 ({article_url}): {e}", file=sys.stderr)
        return ""


def enrich_sources(archive: dict, skip_fetch: bool) -> None:
    """archive内で情報元URL未取得の記事について、記事ページから抽出して保存"""
    targets = [it for it in archive.values() if "source_url" not in it]
    if not targets:
        return
    if skip_fetch:
        for it in targets:
            it.setdefault("source_url", "")
        return
    print(f"情報元リンクを取得中: {len(targets)} 件")
    for it in targets:
        it["source_url"] = fetch_article_source(it["link"])
        time.sleep(1)  # サーバーへの配慮
    ARCHIVE_PATH.write_text(
        json.dumps(archive, ensure_ascii=False, indent=1), encoding="utf-8"
    )

# ------------------------------------------------------------ RSS取得

def fetch_rss(local_file: str | None) -> str:
    if local_file:
        return Path(local_file).read_text(encoding="utf-8")
    req = urllib.request.Request(
        RSS_URL,
        headers={"User-Agent": "Mozilla/5.0 (jnet21-watch; personal use)"},
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read().decode("utf-8")


def parse_items(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        title = (it.findtext("title") or "").strip()
        desc = (it.findtext("description") or "").strip()

        region = ""
        cov = it.find("dc:coverage", NS)
        if cov is not None:
            label = cov.find("rdf:label", NS)
            if label is not None and label.text:
                region = label.text.strip()

        subject = (it.findtext("dc:subject", default="", namespaces=NS) or "").strip()
        kind = subject.split(" - ")[-1] if " - " in subject else "補助金・助成金"

        pub = (it.findtext("dc:date", default="", namespaces=NS) or "").strip()

        m = re.search(r"/articles/(\d+)", link)
        art_id = m.group(1) if m else link

        if region in TARGET_REGIONS and link:
            items.append({
                "id": art_id,
                "title": title,
                "link": link,
                "description": desc,
                "region": region,
                "kind": kind,
                "pub_date": pub,
            })
    return items

# -------------------------------------------------------- 新着の判定

def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def update_state(items: list[dict], today: str) -> dict:
    seen: dict = load_json(SEEN_PATH, {})
    archive: dict = load_json(ARCHIVE_PATH, {})

    for it in items:
        if it["id"] not in seen:
            seen[it["id"]] = today
            it["first_seen"] = today
            archive[it["id"]] = it

    cutoff_seen = (datetime.now(JST) - timedelta(days=SEEN_KEEP_DAYS)).strftime("%Y-%m-%d")
    seen = {k: v for k, v in seen.items() if v >= cutoff_seen}
    cutoff_arc = (datetime.now(JST) - timedelta(days=ARCHIVE_DAYS)).strftime("%Y-%m-%d")
    archive = {k: v for k, v in archive.items() if v.get("first_seen", "") >= cutoff_arc}

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")
    ARCHIVE_PATH.write_text(json.dumps(archive, ensure_ascii=False, indent=1), encoding="utf-8")

    return archive

# ------------------------------------------------ 締切・期日の解析

DEADLINE_LINE_RE = re.compile(
    r"^.{0,12}?(?:申請|募集|公募|受付|応募|要望|提出|取扱|交付申請|申込)"
    r".{0,8}?(?:期間|期限|締切|開始|受付期間|締め切り)日?[：:].*$"
)

DATE_PAT = re.compile(r"(?:(令和|平成)\s*(\d{1,2})年|(\d{4})年)?\s*(\d{1,2})月\s*(\d{1,2})日")


def find_deadline_line(desc: str) -> str:
    for line in desc.splitlines():
        line = line.strip()
        if DEADLINE_LINE_RE.match(line):
            return line
    return ""


def parse_dates_in_line(line: str) -> list[date]:
    """行内の日付をすべて抽出（年の省略は直前の年を引き継ぐ）"""
    dates, year = [], None
    for m in DATE_PAT.finditer(line):
        era, ey, wy, mo, dy = m.groups()
        if era == "令和":
            year = 2018 + int(ey)
        elif era == "平成":
            year = 1988 + int(ey)
        elif wy:
            year = int(wy)
        if year is None:
            continue
        try:
            dates.append(date(year, int(mo), int(dy)))
        except ValueError:
            pass
    return dates


def wareki_short(d: date) -> str:
    if d.year >= 2019:
        return f"R{d.year - 2018}.{d.month}.{d.day}"
    return f"{d.year}.{d.month}.{d.day}"


def deadline_info(desc: str, today: date) -> dict:
    """締切表示用の情報 {cls, main, sub, full, days}"""
    line = find_deadline_line(desc)
    if not line:
        return {"cls": "none", "main": "—", "sub": "期日は詳細参照", "full": "", "days": 9999}

    dates = parse_dates_in_line(line)
    is_start_only = ("開始" in line) and not re.search(r"締切|期限|まで|〆|終了", line)

    if is_start_only and dates:
        start = dates[0]
        if start <= today:
            return {"cls": "safe", "main": "受付中", "sub": f"{wareki_short(start)} 取扱開始", "full": line, "days": 9000}
        n = (start - today).days
        return {"cls": "soon", "main": f"開始まで{n}日", "sub": f"{wareki_short(start)} 開始予定", "full": line, "days": 8000 + n}

    if dates:
        end = dates[-1]
        n = (end - today).days
        if n < 0:
            return {"cls": "none", "main": "受付終了", "sub": f"〜 {wareki_short(end)}", "full": line, "days": 9998}
        if len(dates) >= 2:
            sub = f"{wareki_short(dates[0])} 〜 {wareki_short(end)}"
        else:
            sub = f"〜 {wareki_short(end)}"
        cls = "urgent" if n <= URGENT_DAYS else ("soon" if n <= SOON_DAYS else "safe")
        return {"cls": cls, "main": f"残り {n}日", "sub": sub, "full": line, "days": n}

    # 行はあるが日付を読めなかった場合は原文を短く表示
    short = line if len(line) <= 28 else line[:28] + "…"
    return {"cls": "none", "main": "期日あり", "sub": short, "full": line, "days": 9500}

# ------------------------------------------------ 表示用ヘルパ

def extract_org(desc: str) -> str:
    m = re.match(r"【(.+?)】", desc.strip())
    return m.group(1) if m else ""


def summarize(desc: str, limit: int = 60) -> str:
    text = re.sub(r"^【.+?】", "", desc.strip())
    text = re.sub(r"^（.+?）", "", text.strip())
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"申[込請]方法ほか.*?ご確認ください。?", "", text)
    text = text.strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def region_short(region: str) -> str:
    return region.replace("県", "")


def row_html(it: dict, today: date) -> str:
    color = REGION_COLORS.get(it["region"], "#17425F")
    dl = deadline_info(it["description"], today)
    org = extract_org(it["description"])
    org_sub = f"{escape(org)}｜{escape(summarize(it['description']))}" if org else escape(summarize(it["description"]))
    src = it.get("source_url", "")
    if src:
        org_sub += f'　<a class="mini-src" href="{escape(src)}" target="_blank" rel="noopener">公式↗</a>'
    kind = it.get("kind", "")
    kind_style = ' style="background:#F3EDE2; color:#6B5233;"' if "融資" in kind or "貸付" in kind else ""
    full_attr = f' title="{escape(dl["full"])}"' if dl["full"] else ""
    detail_href = f'articles/{escape(it["id"])}.html'
    return f'''
        <tr data-region="{escape(it["region"])}">
          <td><span class="r-tag" style="--rc:{color}">{escape(region_short(it["region"]))}</span></td>
          <td><span class="k-tag"{kind_style}>{escape(kind)}</span></td>
          <td class="t-title"><a href="{detail_href}">{escape(it["title"])}</a>
            <span class="t-org">{org_sub}</span></td>
          <td class="dcell"{full_attr}><span class="dl {dl["cls"]}">{escape(dl["main"])}</span><span class="dl-date">{escape(dl["sub"])}</span></td>
        </tr>'''


def table_html(items: list[dict], today: date, tbody_id: str = "") -> str:
    rows = "\n".join(row_html(it, today) for it in items)
    idattr = f' id="{tbody_id}"' if tbody_id else ""
    return f'''
    <table>
      <thead><tr><th>地域</th><th>種別</th><th>案件名</th><th>締切まで</th></tr></thead>
      <tbody{idattr}>{rows}</tbody>
    </table>'''

# ------------------------------------------------------ ページ生成

def build_page(archive: dict, now: datetime) -> str:
    today_str = now.strftime("%Y-%m-%d")
    today_d = now.date()
    wd = "月火水木金土日"[now.weekday()]

    def sort_key(it):
        return (TARGET_REGIONS.index(it["region"]), it["title"])

    new_sorted = sorted(
        [it for it in archive.values() if it.get("first_seen") == today_str],
        key=sort_key,
    )
    counts = {r: sum(1 for i in new_sorted if i["region"] == r) for r in TARGET_REGIONS}

    kpi_region = "".join(
        f'''<div class="kpi" data-filter="{escape(r)}" style="--rc:{REGION_COLORS[r]}">
              <div class="label">{escape(region_short(r))}</div><div class="num">{counts[r]}</div></div>'''
        for r in TARGET_REGIONS
    )

    if new_sorted:
        today_table = table_html(new_sorted, today_d, tbody_id="todayBody")
    else:
        today_table = '<p class="empty">本日の対象地域の新着はありませんでした。</p>'

    # 過去の新着
    past: dict[str, list[dict]] = {}
    for it in archive.values():
        d = it.get("first_seen", "")
        if d and d != today_str:
            past.setdefault(d, []).append(it)

    past_parts = []
    for d in sorted(past.keys(), reverse=True):
        items_d = sorted(past[d], key=sort_key)
        dt = datetime.strptime(d, "%Y-%m-%d")
        wd2 = "月火水木金土日"[dt.weekday()]
        past_parts.append(f'''
      <details class="day-block">
        <summary>{dt.month}月{dt.day}日（{wd2}）<span class="day-count">{len(items_d)}件</span></summary>
        {table_html(items_d, today_d)}
      </details>''')
    past_section = "\n".join(past_parts) if past_parts else '<p class="empty">まだ履歴がありません。</p>'

    updated = now.strftime("%Y-%m-%d %H:%M")

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>支援情報モニター｜補助金・助成金・融資</title>
<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#17425F">
<link rel="icon" type="image/png" href="icon-192.png">
<link rel="apple-touch-icon" href="icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="新着補助金">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700;900&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:#F4F6F8; --panel:#FFFFFF; --ink:#17242F; --sub:#63707C; --line:#E1E7EC;
    --navy:#17425F; --warn:#C7391B; --caution:#B07C10; --ok:#1E7A4C;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--ink); font-family:"Noto Sans JP",sans-serif; line-height:1.6; }}

  .topbar {{ background:var(--navy); color:#fff; padding:14px 20px; }}
  .topbar-inner {{ max-width:1080px; margin:0 auto; display:flex; align-items:center; gap:14px; flex-wrap:wrap; }}
  .logo {{ font-weight:900; font-size:1.02rem; letter-spacing:.04em; }}
  .logo::before {{ content:"●"; color:#5FD08A; margin-right:8px; font-size:.7rem; vertical-align:2px; }}
  .sync {{ margin-left:auto; font-family:"IBM Plex Mono",monospace; font-size:.72rem; opacity:.85; }}

  main {{ max-width:1080px; margin:0 auto; padding:20px 16px 60px; }}

  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(110px,1fr)); gap:10px; }}
  .kpi {{ background:var(--panel); border:1px solid var(--line); border-radius:10px;
         padding:12px 14px; border-top:4px solid var(--rc,var(--navy)); cursor:pointer; user-select:none; }}
  .kpi.active {{ outline:2px solid var(--rc,var(--navy)); }}
  .kpi .label {{ font-size:.74rem; font-weight:700; color:var(--sub); }}
  .kpi .num {{ font-family:"IBM Plex Mono",monospace; font-size:1.7rem; font-weight:600; line-height:1.2; }}
  .kpi .num small {{ font-size:.72rem; font-family:"Noto Sans JP"; color:var(--sub); font-weight:500; }}

  .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; margin-top:16px; overflow:hidden; }}
  .panel-head {{ display:flex; align-items:center; gap:10px; padding:12px 16px; border-bottom:1px solid var(--line); flex-wrap:wrap; }}
  .panel-head h2 {{ font-size:.95rem; font-weight:700; }}
  .badge-new {{ background:var(--warn); color:#fff; font-size:.7rem; font-weight:700;
               border-radius:999px; padding:1px 10px; }}
  .search {{ margin-left:auto; border:1px solid var(--line); border-radius:8px; padding:5px 10px;
            font-size:.8rem; font-family:inherit; width:190px; }}

  table {{ width:100%; border-collapse:collapse; font-size:.84rem; }}
  thead th {{ text-align:left; font-size:.7rem; color:var(--sub); font-weight:700;
             padding:8px 12px; border-bottom:1px solid var(--line); background:#FAFBFC; white-space:nowrap; }}
  tbody td {{ padding:12px; border-bottom:1px solid var(--line); vertical-align:top; }}
  tbody tr:last-child td {{ border-bottom:none; }}
  tbody tr:hover {{ background:#F6FAFD; }}
  .r-tag {{ display:inline-block; font-size:.72rem; font-weight:700; color:#fff;
           background:var(--rc,var(--navy)); border-radius:4px; padding:1px 8px; white-space:nowrap; }}
  .k-tag {{ display:inline-block; font-size:.72rem; font-weight:700; color:var(--sub);
           background:#EEF2F5; border-radius:4px; padding:1px 8px; white-space:nowrap; }}
  .t-title {{ font-weight:700; }}
  .t-title a {{ color:var(--ink); text-decoration:none; }}
  .t-title a:hover {{ color:var(--navy); text-decoration:underline; }}
  .t-org {{ display:block; font-size:.74rem; color:var(--sub); font-weight:400; margin-top:2px; }}
  .mini-src {{ font-size:.72rem; font-weight:700; color:var(--navy) !important; text-decoration:none;
              border:1px solid var(--line); border-radius:4px; padding:0 6px; white-space:nowrap; }}
  .mini-src:hover {{ background:#EDF3F8; }}

  .dcell {{ white-space:nowrap; }}
  .dl {{ font-family:"IBM Plex Mono",monospace; font-weight:600; font-size:.9rem; display:block; }}
  .dl.urgent {{ color:var(--warn); }}
  .dl.soon {{ color:var(--caution); }}
  .dl.safe {{ color:var(--ok); }}
  .dl.none {{ color:var(--sub); font-family:"Noto Sans JP"; font-size:.8rem; }}
  .dl-date {{ display:block; font-size:.7rem; color:var(--sub); }}

  .day-block summary {{ cursor:pointer; padding:12px 16px; font-weight:700; font-size:.9rem; list-style:none;
                       display:flex; align-items:center; gap:10px; border-bottom:1px solid var(--line); }}
  .day-block summary::before {{ content:"▸"; color:var(--navy); transition:transform .15s; }}
  .day-block[open] summary::before {{ transform:rotate(90deg); }}
  .day-count {{ font-size:.72rem; font-weight:700; color:var(--sub); background:#EEF2F5;
               border-radius:999px; padding:1px 10px; }}

  .empty {{ padding:26px; text-align:center; color:var(--sub); font-size:.9rem; }}
  footer {{ max-width:1080px; margin:0 auto; padding:14px 16px 40px; font-size:.72rem; color:var(--sub); }}
  footer a {{ color:var(--sub); }}

  @media (max-width:640px) {{
    thead {{ display:none; }}
    tbody td {{ display:block; border-bottom:none; padding:3px 14px; }}
    tbody tr {{ display:block; border-bottom:1px solid var(--line); padding:9px 0; }}
    tbody tr:hover {{ background:none; }}
    .search {{ width:100%; margin-left:0; }}
  }}
</style>
</head>
<body>

<header class="topbar">
  <div class="topbar-inner">
    <div class="logo">支援情報モニター｜補助金・助成金・融資</div>
    <div class="sync">LAST SYNC {updated} JST</div>
  </div>
</header>

<div id="staleBanner" style="display:none; background:#C7391B; color:#fff; text-align:center;
     font-size:.85rem; font-weight:700; padding:9px 14px;">
  ⚠️ 最終更新から<span id="staleHours"></span>時間以上経過しています。自動更新が止まっている可能性があります。
  <a href="https://github.com/SOIJAPAN/jnet21-watch/actions" target="_blank" rel="noopener"
     style="color:#fff;">実行状況を確認 ↗</a>
</div>

<main>
  <div class="kpis" id="kpis">
    <div class="kpi active" data-filter="all" style="--rc:var(--ink)">
      <div class="label">本日の新着 {now.month}/{now.day}（{wd}）</div>
      <div class="num">{len(new_sorted)}<small> 件</small></div>
    </div>
    {kpi_region}
  </div>

  <div class="panel">
    <div class="panel-head">
      <h2>本日の新着トピック</h2><span class="badge-new">NEW {len(new_sorted)}</span>
      <input class="search" id="searchBox" type="search" placeholder="キーワード検索…">
    </div>
    {today_table}
  </div>

  <div class="panel">
    <div class="panel-head"><h2>過去の新着（直近{ARCHIVE_DAYS}日）</h2></div>
    {past_section}
  </div>
</main>

<footer>
  情報元：<a href="https://j-net21.smrj.go.jp/snavi2/index.html" target="_blank" rel="noopener">J-Net21 支援情報ヘッドライン</a>（独立行政法人 中小企業基盤整備機構）｜毎日 午前2時 自動更新｜残り日数は説明文の期日記載から自動計算した参考値です。正確な締切は必ず各制度の公式ページでご確認ください。
</footer>

<script>
  const kpis = document.getElementById('kpis');
  const searchBox = document.getElementById('searchBox');
  const rows = () => document.querySelectorAll('#todayBody tr');
  let regionFilter = 'all';

  function apply() {{
    const q = (searchBox?.value || '').trim().toLowerCase();
    rows().forEach(tr => {{
      const okRegion = regionFilter === 'all' || tr.dataset.region === regionFilter;
      const okText = !q || tr.textContent.toLowerCase().includes(q);
      tr.style.display = (okRegion && okText) ? '' : 'none';
    }});
  }}
  if (kpis) kpis.addEventListener('click', e => {{
    const k = e.target.closest('.kpi');
    if (!k) return;
    kpis.querySelectorAll('.kpi').forEach(x => x.classList.remove('active'));
    k.classList.add('active');
    regionFilter = k.dataset.filter;
    apply();
  }});
  if (searchBox) searchBox.addEventListener('input', apply);

  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js');

  // 死活監視：最終更新から27時間を超えていたら警告バナーを表示
  (function() {{
    const lastSync = new Date('{now.strftime("%Y-%m-%dT%H:%M:%S")}+09:00');
    const hours = (Date.now() - lastSync.getTime()) / 3600000;
    if (hours > 27) {{
      document.getElementById('staleHours').textContent = Math.floor(hours);
      document.getElementById('staleBanner').style.display = 'block';
    }}
  }})();
</script>
</body>
</html>
'''

# ---------------------------------------------------- 概要説明ページ

def build_detail_page(it: dict, today: date) -> str:
    color = REGION_COLORS.get(it["region"], "#17425F")
    dl = deadline_info(it["description"], today)
    org = extract_org(it["description"])
    src = it.get("source_url", "")
    kind = it.get("kind", "")
    kind_style = ' style="background:#F3EDE2; color:#6B5233;"' if "融資" in kind or "貸付" in kind else ""

    # 本文（定型の案内文を除いて改行を保持）
    body = it["description"]
    body = re.sub(r"申[込請]方法ほか.*?ご確認ください。?", "", body).strip()
    body_html = escape(body).replace("\n", "<br>")

    first_seen = it.get("first_seen", "")
    seen_disp = ""
    if first_seen:
        try:
            fs = datetime.strptime(first_seen, "%Y-%m-%d")
            seen_disp = f"{fs.year}年{fs.month}月{fs.day}日 掲載確認"
        except ValueError:
            pass

    if src:
        cta = f'''
      <a class="btn primary" href="{escape(src)}" target="_blank" rel="noopener">情報元の公式ページを見る ↗</a>
      <a class="btn secondary" href="{escape(it["link"])}" target="_blank" rel="noopener">J-Net21掲載ページ ↗</a>'''
        src_note = f'<p class="src-note">情報元：{escape(urlparse(src).netloc)}</p>'
    else:
        cta = f'''
      <a class="btn primary" href="{escape(it["link"])}" target="_blank" rel="noopener">J-Net21掲載ページで詳細を見る ↗</a>'''
        src_note = '<p class="src-note">情報元の公式リンクを自動取得できなかったため、J-Net21の掲載ページからご確認ください。</p>'

    dl_block = ""
    if dl["cls"] != "none" or dl["full"]:
        dl_block = f'''
    <div class="dl-box {dl["cls"]}">
      <span class="dl-main">{escape(dl["main"])}</span>
      <span class="dl-sub">{escape(dl["full"] or dl["sub"])}</span>
    </div>'''

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(it["title"])}｜支援情報モニター</title>
<meta name="theme-color" content="#17425F">
<link rel="icon" type="image/png" href="../icon-192.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700;900&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:#F4F6F8; --panel:#FFFFFF; --ink:#17242F; --sub:#63707C; --line:#E1E7EC;
    --navy:#17425F; --warn:#C7391B; --caution:#B07C10; --ok:#1E7A4C;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--ink); font-family:"Noto Sans JP",sans-serif; line-height:1.8; }}
  .topbar {{ background:var(--navy); color:#fff; padding:12px 20px; }}
  .topbar-inner {{ max-width:760px; margin:0 auto; display:flex; align-items:center; gap:14px; }}
  .back {{ color:#fff; text-decoration:none; font-size:.85rem; font-weight:700; }}
  .back:hover {{ text-decoration:underline; }}
  main {{ max-width:760px; margin:0 auto; padding:20px 16px 60px; }}
  .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:12px;
           border-top:5px solid {color}; padding:22px 22px 26px; }}
  .meta {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
  .r-tag {{ font-size:.74rem; font-weight:700; color:#fff; background:{color}; border-radius:4px; padding:1px 10px; }}
  .k-tag {{ font-size:.74rem; font-weight:700; color:var(--sub); background:#EEF2F5; border-radius:4px; padding:1px 10px; }}
  .seen {{ font-size:.72rem; color:var(--sub); margin-left:auto; }}
  h1 {{ font-size:1.15rem; font-weight:900; line-height:1.6; margin-top:12px; }}
  .org {{ font-size:.82rem; color:var(--sub); margin-top:4px; }}
  .dl-box {{ display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; margin-top:16px;
            border-radius:10px; padding:12px 16px; background:#F1F5F3; }}
  .dl-box.urgent {{ background:#FBEDE9; }} .dl-box.soon {{ background:#FAF3E3; }}
  .dl-main {{ font-family:"IBM Plex Mono",monospace; font-weight:600; font-size:1.15rem; }}
  .dl-box.urgent .dl-main {{ color:var(--warn); }} .dl-box.soon .dl-main {{ color:var(--caution); }}
  .dl-box.safe .dl-main {{ color:var(--ok); }}
  .dl-sub {{ font-size:.8rem; color:var(--sub); }}
  .body-text {{ margin-top:18px; font-size:.9rem; border-top:1px solid var(--line); padding-top:16px; }}
  .cta {{ margin-top:24px; display:flex; flex-direction:column; gap:10px; }}
  .btn {{ display:block; text-align:center; font-weight:700; font-size:.95rem; text-decoration:none;
         border-radius:10px; padding:13px 16px; }}
  .btn.primary {{ background:var(--navy); color:#fff; }}
  .btn.primary:hover {{ background:#0F3049; }}
  .btn.secondary {{ background:#fff; color:var(--navy); border:1.5px solid var(--navy); }}
  .btn.secondary:hover {{ background:#EDF3F8; }}
  .src-note {{ font-size:.74rem; color:var(--sub); margin-top:8px; text-align:center; }}
  footer {{ max-width:760px; margin:0 auto; padding:14px 16px 40px; font-size:.72rem; color:var(--sub); }}
</style>
</head>
<body>
<header class="topbar">
  <div class="topbar-inner"><a class="back" href="../index.html">← 一覧へ戻る</a></div>
</header>
<main>
  <div class="panel">
    <div class="meta">
      <span class="r-tag">{escape(it["region"])}</span>
      <span class="k-tag"{kind_style}>{escape(kind)}</span>
      <span class="seen">{escape(seen_disp)}</span>
    </div>
    <h1>{escape(it["title"])}</h1>
    {f'<p class="org">実施機関：{escape(org)}</p>' if org else ''}
    {dl_block}
    <div class="body-text">{body_html}</div>
    <div class="cta">{cta}</div>
    {src_note}
  </div>
</main>
<footer>本ページはJ-Net21 支援情報ヘッドライン（中小機構）の掲載内容をもとに自動生成した概要です。募集要件・締切等の正確な情報は必ず情報元の公式ページでご確認ください。</footer>
</body>
</html>
'''


def write_detail_pages(archive: dict, today: date) -> None:
    art_dir = DOCS_DIR / "articles"
    # 一旦クリアして、保持期間内の記事だけを再生成
    if art_dir.exists():
        for f in art_dir.glob("*.html"):
            f.unlink()
    art_dir.mkdir(parents=True, exist_ok=True)
    for it in archive.values():
        (art_dir / f"{it['id']}.html").write_text(
            build_detail_page(it, today), encoding="utf-8"
        )
    print(f"概要説明ページ: {len(archive)} 件生成")

# --------------------------------------------------------- PWA出力

def write_pwa_files():
    manifest = {
        "name": "支援情報モニター（補助金・助成金・融資）",
        "short_name": "新着補助金",
        "description": "全国・愛知・岐阜・静岡・三重の補助金・助成金・融資の新着情報を毎日チェック",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": "#F4F6F8",
        "theme_color": "#17425F",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    (DOCS_DIR / "manifest.webmanifest").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    sw = """// ネットワーク優先＋オフライン時はキャッシュ表示
const CACHE = 'jnet21-watch-v3';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(clients.claim()));
self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET' || !e.request.url.startsWith(self.location.origin)) return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
"""
    (DOCS_DIR / "sw.js").write_text(sw, encoding="utf-8")

# ------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="ローカルXMLファイルでテスト", default=None)
    args = ap.parse_args()

    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")

    xml_text = fetch_rss(args.file)
    items = parse_items(xml_text)
    print(f"対象地域の記事: {len(items)} 件")

    archive = update_state(items, today)
    new_count = sum(1 for it in archive.values() if it.get("first_seen") == today)
    print(f"本日の新着: {new_count} 件")

    # 情報元リンクの取得（ローカルテスト時はスキップ）
    enrich_sources(archive, skip_fetch=bool(args.file))

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "index.html").write_text(build_page(archive, now), encoding="utf-8")
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")
    write_detail_pages(archive, now.date())
    write_pwa_files()
    print("docs/index.html を生成しました")


if __name__ == "__main__":
    main()
