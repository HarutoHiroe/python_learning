#!/usr/bin/env python3
"""
武豊線 抜け道乗換アシスト（2026年ダイヤ）
亀崎 → 武豊方面に先乗り → 乙川/半田/東成岩 で大府行きに乗換

【データ取得の優先順位】
  1. JR東海公式PDF  railway.jr-central.co.jp（一次ソース・駅掲示と同一）
  2. Yahoo!路線情報  transit.yahoo.co.jp（JR時刻表準拠・HTMLスクレイピング）
  3. 内蔵データ      2026年4月ダイヤ・平日（完全オフライン）

【使い方】
  python3 taketoyo_hayawari.py              # 現在時刻・自動曜日
  python3 taketoyo_hayawari.py 8:30         # 時刻指定（今日の曜日）
  python3 taketoyo_hayawari.py 16:00 2      # 時刻+曜日(1=平日 2=土 4=日祝)
  python3 taketoyo_hayawari.py --offline    # 内蔵データのみ（高速）
  python3 taketoyo_hayawari.py --source     # どのソースを使ったか表示

【必要ライブラリ（初回のみ）】
  pip3 install requests beautifulsoup4 pdfplumber
"""

import sys, re, time, io
from datetime import datetime, date
from typing import Optional

# ── ライブラリ ────────────────────────────────────────────────
try:
    import requests
    from bs4 import BeautifulSoup
    import pdfplumber
    HAS_LIBS = True
except ImportError:
    HAS_LIBS = False

# ── 定数 ─────────────────────────────────────────────────────
TRAVEL_MINS      = {"乙川": 3,  "半田": 6,  "東成岩": 9}
TO_DAFU          = {"乙川": 28, "半田": 25, "東成岩": 22}
KAME_DAFU_DIRECT = 32   # 亀崎→大府 直通所要分
MIN_TRANSFER     = 1    # 乗換最低待ち時間

# JR東海公式PDF（武豊線・大府名古屋方面 全駅一括）
# ファイル名パターン: {路線}_{代表駅}_{区分}_{曜日}_{方向}.pdf
JR_PDF = {
    "base": "https://railway.jr-central.co.jp/time-schedule/srch/_pdf/data",
    # 平日・土日祝で別ファイル
    "weekday":  "202503/taketoyo_Taketoyo_B_w_u.pdf",
    "holiday":  "202503/taketoyo_Taketoyo_B_h_u.pdf",
    # 武豊方面(下り)は別PDF
    "weekday_d": "202503/taketoyo_Obu_A_w_d.pdf",
    "holiday_d": "202503/taketoyo_Obu_A_h_d.pdf",
}

# Yahoo!路線情報 駅ID
YAHOO_IDS = {
    "亀崎_up":     ("24890", "1430"),   # 武豊方面
    "亀崎_down":   ("24890", "1431"),   # 大府方面
    "乙川_down":   ("24838", "1431"),
    "半田_down":   ("25107", "1431"),
    "東成岩_down": ("25117", "1431"),
}
YAHOO_BASE = "https://transit.yahoo.co.jp/timetable/{sid}/{did}"

# PDF内の駅名（英語キー → 日本語）
PDF_STATION_MAP = {
    "Kamezaki": "亀崎",
    "Okkawa":   "乙川",
    "Handa":    "半田",
    "Higashi-Narawa": "東成岩",
    "Taketoyo": "武豊",
    "Obu":      "大府",
}
# PDF内で大府方面時刻表に出てくる駅順（武豊側→大府側）
PDF_STATIONS_U = ["Taketoyo","Higashi-Narawa","Handa","Okkawa","Kamezaki",
                  "Higashiura","Ishihama","Ogawa","Owari-Morioka","Obu"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    "Referer": "https://railway.jr-central.co.jp/",
}

# ── カラー ────────────────────────────────────────────────────
RST = "\033[0m";  BOLD = "\033[1m"
BLU = "\033[34m"; GRN  = "\033[32m"; YLW = "\033[33m"
RED = "\033[31m"; GRY  = "\033[90m"; CYN = "\033[36m"
LABELS = ["A", "B", "C"]

def fmt(m: int) -> str:
    return f"{m//60}:{m%60:02d}"

# ── 2026年4月 内蔵データ（平日）────────────────────────────
def _t(p): return sorted(h*60+m for h,m in p)

BUILTIN: dict[str, list[int]] = {
    "亀崎_up": _t([
        (6,16),(6,30),(6,55),(7,11),(7,33),(7,57),(8,8),(8,33),(9,12),(9,33),
        (10,7),(10,37),(11,7),(11,37),(12,7),(12,37),(13,7),(13,37),(14,7),(14,37),
        (15,7),(15,37),(16,1),(16,24),(16,59),(17,23),(17,53),(18,19),(18,37),
        (19,3),(19,33),(20,5),(20,37),(21,9),(21,40),(22,13),(22,45),(23,15),
    ]),
    "亀崎_down": _t([
        (5,36),(6,5),(6,38),(6,55),(7,11),(7,33),(7,48),(8,8),(8,33),(8,47),
        (9,12),(9,48),(10,21),(10,51),(11,21),(11,51),(12,21),(12,51),(13,21),(13,51),
        (14,21),(14,51),(15,21),(15,45),(16,15),(16,38),(17,8),(17,37),(18,8),(18,37),
        (19,7),(19,31),(20,6),(20,40),(21,9),(21,45),(22,15),(22,45),(23,15),
    ]),
    "乙川_down": _t([
        (5,33),(6,2),(6,34),(6,50),(7,6),(7,25),(7,44),(8,3),(8,28),(8,43),
        (9,9),(9,45),(10,17),(10,47),(11,17),(11,47),(12,17),(12,47),(13,17),(13,47),
        (14,17),(14,47),(15,17),(15,41),(16,11),(16,34),(17,4),(17,34),(18,4),(18,34),
        (19,4),(19,28),(20,3),(20,37),(21,6),(21,42),(22,12),(22,42),(23,12),
    ]),
    "半田_down": _t([
        (5,36),(6,5),(6,37),(6,53),(7,9),(7,28),(7,47),(8,6),(8,31),(8,46),
        (9,12),(9,48),(10,20),(10,50),(11,20),(11,50),(12,20),(12,50),(13,20),(13,50),
        (14,20),(14,50),(15,20),(15,44),(16,14),(16,37),(17,7),(17,37),(18,7),(18,37),
        (19,7),(19,31),(20,6),(20,40),(21,9),(21,45),(22,15),(22,45),(23,15),
    ]),
    "東成岩_down": _t([
        (5,27),(5,56),(6,27),(6,43),(6,58),(7,18),(7,37),(7,56),(8,21),(8,36),
        (9,3),(9,38),(10,10),(10,40),(11,10),(11,40),(12,10),(12,32),(13,10),(13,40),
        (14,10),(14,40),(15,10),(15,34),(16,3),(16,28),(16,58),(17,28),(17,55),
        (18,22),(18,48),(19,15),(19,43),(20,14),(20,48),(21,17),(21,54),(22,24),(22,54),(23,24),
    ]),
}

# ════════════════════════════════════════════════════════════
#  1. JR東海公式PDF 取得 & パース
# ════════════════════════════════════════════════════════════

def _pdf_url(day_type: int, direction: str) -> list[str]:
    """試すべきPDF URLリストを返す（命名パターンが複数あるため候補を列挙）"""
    base = JR_PDF["base"]
    ym = "202503"  # ダイヤ改正月
    if direction == "up":   # 大府・名古屋方面
        suffixes = ["w" if day_type == 1 else "h"]
        candidates = [
            f"{base}/{ym}/taketoyo_Taketoyo_B_{s}_u.pdf"  for s in suffixes
        ] + [
            f"{base}/{ym}/taketoyo_Taketoyo_B_wh_u.pdf",
        ]
    else:                   # 武豊方面
        suffixes = ["w" if day_type == 1 else "h"]
        candidates = [
            f"{base}/{ym}/taketoyo_Obu_A_{s}_d.pdf"       for s in suffixes
        ] + [
            f"{base}/{ym}/taketoyo_Obu_A_wh_d.pdf",
        ]
    return candidates


def _fetch_pdf_bytes(day_type: int, direction: str, session) -> Optional[bytes]:
    for url in _pdf_url(day_type, direction):
        try:
            r = session.get(url, timeout=15)
            if r.status_code == 200 and r.headers.get("content-type","").startswith("application/pdf"):
                return r.content
        except Exception:
            pass
    return None


def _parse_pdf_timetable(pdf_bytes: bytes) -> dict[str, list[int]]:
    """
    JR東海時刻表PDFをパースして {駅キー: [分単位時刻リスト]} を返す。

    PDFレイアウト想定:
      - 1行目ヘッダ: 駅名（英語）が横並び
      - 以降: 時(左端) + 各駅の発車分 が横並び
      - 平日/土日は別ページ（page 0=平日 or ページタイトルで判定）
    """
    result: dict[str, list[int]] = {}
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                words = page.extract_words(x_tolerance=3, y_tolerance=3)
                if not words:
                    continue

                # ── 駅名行を検出 ──────────────────────────────
                # 英語駅名（大文字始まり・ハイフン含む可能性）が横並びの行を探す
                station_cols: dict[str, float] = {}  # 英語駅名 → x座標
                rows_by_y: dict[float, list] = {}
                for w in words:
                    y_key = round(w["top"], 1)
                    rows_by_y.setdefault(y_key, []).append(w)

                sorted_ys = sorted(rows_by_y)
                header_y = None
                for y in sorted_ys:
                    row_words = [w["text"] for w in rows_by_y[y]]
                    matched = [w for w in row_words if w in PDF_STATION_MAP]
                    if len(matched) >= 2:
                        header_y = y
                        for item in rows_by_y[y]:
                            if item["text"] in PDF_STATION_MAP:
                                station_cols[item["text"]] = item["x0"]
                        break

                if not station_cols:
                    continue  # このページには駅ヘッダがない

                # ── 時刻行を解析 ──────────────────────────────
                # header_y より下の行を処理
                # 左端の数字(0〜23)が「時」、各駅x座標付近の数字が「分」
                hour_col_x = min(item["x0"] for item in rows_by_y.get(header_y, [{"x0":0}]))

                for y in sorted_ys:
                    if y <= header_y:
                        continue
                    row = sorted(rows_by_y[y], key=lambda w: w["x0"])
                    if not row:
                        continue

                    # 先頭トークンが時(0-23)かチェック
                    first = row[0]["text"].strip()
                    if not re.fullmatch(r"\d{1,2}", first):
                        continue
                    hour = int(first)
                    if not (0 <= hour <= 23):
                        continue

                    # 各駅列に対して最も近いx座標のトークンを「分」として取る
                    for st_en, col_x in station_cols.items():
                        st_ja = PDF_STATION_MAP[st_en]
                        # col_x ± 20px 内のトークンを候補とする
                        candidates = [
                            w for w in row[1:]
                            if abs(w["x0"] - col_x) < 20
                            and re.fullmatch(r"\d{1,2}", w["text"].strip())
                        ]
                        for c in candidates:
                            minute = int(c["text"].strip())
                            if 0 <= minute <= 59:
                                key = f"{st_ja}_down" if "up" not in page.page_number.__class__.__name__ else f"{st_ja}_up"
                                # 大府方面PDFなら _down、武豊方面PDFなら _up
                                result.setdefault(st_ja + "_down", []).append(hour * 60 + minute)

    except Exception as e:
        print(f"  {YLW}PDF解析エラー: {e}{RST}")

    # ソート・重複除去
    return {k: sorted(set(v)) for k, v in result.items()}


def fetch_jrcentral(day_type: int) -> Optional[dict[str, list[int]]]:
    if not HAS_LIBS:
        return None
    print(f"  {GRY}[1/3] JR東海公式PDFから取得中...{RST}", flush=True)
    session = requests.Session()
    session.headers.update(HEADERS)

    # 大府方面PDF（上り: 亀崎→大府方向）
    pdf_up = _fetch_pdf_bytes(day_type, "up", session)
    # 武豊方面PDF（下り: 亀崎→武豊方向）
    pdf_down = _fetch_pdf_bytes(day_type, "down", session)

    if not pdf_up and not pdf_down:
        print(f"  {YLW}  JR東海PDF: 取得失敗（URLパターン不一致 or アクセス制限）{RST}")
        return None

    result: dict[str, list[int]] = {}

    if pdf_up:
        parsed = _parse_pdf_timetable(pdf_up)
        result.update(parsed)
        keys = [k for k in parsed if k.endswith("_down")]
        print(f"  {GRY}  大府方面PDF: {len(keys)}駅分 取得{RST}")
    else:
        print(f"  {YLW}  大府方面PDF: 取得失敗{RST}")

    if pdf_down:
        # 武豊方面は亀崎_up のみ必要
        parsed_d = _parse_pdf_timetable(pdf_down)
        # _down キーを _up に付け替え（武豊行きPDFは方向が逆）
        for k, v in parsed_d.items():
            result[k.replace("_down", "_up")] = v
        print(f"  {GRY}  武豊方面PDF: 亀崎発時刻 {len(result.get('亀崎_up',[]))}便{RST}")
    else:
        print(f"  {YLW}  武豊方面PDF: 取得失敗{RST}")

    if not result:
        return None

    # 必須キーが揃っているか確認
    required = {"亀崎_up", "亀崎_down", "乙川_down", "半田_down", "東成岩_down"}
    missing = required - set(result.keys())
    if missing:
        print(f"  {YLW}  PDF不足キー: {missing} → Yahoo補完へ{RST}")

    return result if result else None


# ════════════════════════════════════════════════════════════
#  2. Yahoo!路線情報 スクレイピング
# ════════════════════════════════════════════════════════════

def _parse_yahoo_html(html: str) -> list[int]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []
    times = []
    for row in table.find_all("tr"):
        th = row.find("th")
        if not th or not th.get_text(strip=True).isdigit():
            continue
        hour = int(th.get_text(strip=True))
        for li in row.find_all("li"):
            m = re.match(r"(\d+)", li.get_text(strip=True))
            if m:
                times.append(hour * 60 + int(m.group(1)))
    return sorted(times)


def fetch_yahoo(day_type: int, keys_needed: set[str]) -> dict[str, list[int]]:
    """必要なキーだけYahooから取得して返す"""
    if not HAS_LIBS or not keys_needed:
        return {}

    session = requests.Session()
    session.headers.update({
        **HEADERS,
        "Referer": "https://transit.yahoo.co.jp/",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    })
    try:
        session.get("https://transit.yahoo.co.jp/", timeout=10)
        time.sleep(0.5)
    except Exception:
        pass

    result = {}
    for key in sorted(keys_needed):
        if key not in YAHOO_IDS:
            continue
        sid, did = YAHOO_IDS[key]
        url = YAHOO_BASE.format(sid=sid, did=did)
        try:
            r = session.get(url, params={"kind": day_type}, timeout=12)
            r.raise_for_status()
            times = _parse_yahoo_html(r.text)
            if times:
                result[key] = times
                print(f"  {GRY}  Yahoo {key}: {len(times)}便 ✓{RST}")
            else:
                print(f"  {YLW}  Yahoo {key}: パース失敗{RST}")
        except Exception as e:
            print(f"  {YLW}  Yahoo {key}: {e}{RST}")
        time.sleep(0.5)
    return result


# ════════════════════════════════════════════════════════════
#  統合取得 + クロスチェック
# ════════════════════════════════════════════════════════════

REQUIRED_KEYS = {"亀崎_up", "亀崎_down", "乙川_down", "半田_down", "東成岩_down"}


def _crosscheck(pdf_data: dict, yahoo_data: dict) -> dict[str, list[int]]:
    """
    PDF と Yahoo を突き合わせて不一致を警告し、より信頼できる方を採用する。
    基本方針: JR東海PDF優先。YahooはPDF失敗時の補完 or 差分確認用。
    """
    merged = {}
    all_keys = REQUIRED_KEYS

    for key in all_keys:
        pdf_v   = pdf_data.get(key, [])
        yahoo_v = yahoo_data.get(key, [])

        if pdf_v and yahoo_v:
            # 両方ある → 差分チェック
            pdf_set   = set(pdf_v)
            yahoo_set = set(yahoo_v)
            only_pdf   = pdf_set - yahoo_set
            only_yahoo = yahoo_set - pdf_set

            if only_pdf or only_yahoo:
                print(f"  {YLW}  [{key}] PDF↔Yahoo 差分あり:"
                      f" PDF専用={sorted(fmt(t) for t in only_pdf)}"
                      f" Yahoo専用={sorted(fmt(t) for t in only_yahoo)}{RST}")

            # JR東海PDF を正として採用（臨時増発等は yahoo 側に出やすいが
            # 正規ダイヤの精度は PDF が上）
            merged[key] = pdf_v

        elif pdf_v:
            merged[key] = pdf_v
        elif yahoo_v:
            merged[key] = yahoo_v
        else:
            # 両方なし → 内蔵で補完
            merged[key] = BUILTIN.get(key, [])
            if merged[key]:
                print(f"  {YLW}  [{key}]: 取得失敗 → 内蔵データで補完{RST}")

    return merged


def load_timetables(day_type: int, offline: bool, show_source: bool) -> tuple[dict, str]:
    """
    全時刻データを読み込んで返す。
    Returns: (timetable_dict, source_description)
    """
    if offline:
        return BUILTIN, "内蔵データ（2026年4月・平日）"

    if not HAS_LIBS:
        print(f"  {YLW}requests/bs4/pdfplumber が未インストール → 内蔵データ使用{RST}")
        print(f"  pip3 install requests beautifulsoup4 pdfplumber")
        return BUILTIN, "内蔵データ（ライブラリ未インストール）"

    # Step 1: JR東海PDF
    pdf_data = fetch_jrcentral(day_type) or {}
    missing = REQUIRED_KEYS - set(pdf_data.keys())

    # Step 2: Yahoo!（PDF失敗分 or 全件差分確認）
    yahoo_needed = missing | (REQUIRED_KEYS if show_source else set())
    yahoo_data: dict = {}
    if yahoo_needed:
        print(f"  {GRY}[2/3] Yahoo!路線情報から補完/検証中...{RST}", flush=True)
        yahoo_data = fetch_yahoo(day_type, yahoo_needed)

    # Step 3: クロスチェック & マージ
    merged = _crosscheck(pdf_data, yahoo_data)

    # Step 4: まだ足りないキーは内蔵で補完
    for key in REQUIRED_KEYS:
        if not merged.get(key):
            merged[key] = BUILTIN.get(key, [])

    # ソース説明
    has_pdf   = bool(pdf_data)
    has_yahoo = bool(yahoo_data)
    if has_pdf and has_yahoo:
        src = "JR東海公式PDF + Yahoo!路線情報（クロスチェック済み）"
    elif has_pdf:
        src = "JR東海公式PDF（2026年3月改正）"
    elif has_yahoo:
        src = "Yahoo!路線情報（JR時刻表令和8年3月号）"
    else:
        src = "内蔵データ（2026年4月・平日）"

    total = sum(len(v) for v in merged.values())
    print(f"  {GRY}[3/3] データ準備完了（計 {total} 便）{RST}\n")
    return merged, src


# ════════════════════════════════════════════════════════════
#  乗換計算
# ════════════════════════════════════════════════════════════

def find_next(times: list[int], from_min: int) -> Optional[int]:
    for t in times:
        if t >= from_min:
            return t
    return None


def calc_routes(tt: dict, now_min: int, window_min: int = 180) -> list[dict]:
    kame_up   = tt.get("亀崎_up",   [])
    kame_down = tt.get("亀崎_down", [])
    results = []

    for up_dep in kame_up:
        if up_dep < now_min:
            continue
        if up_dep > now_min + window_min:
            break

        for st in ("乙川", "半田", "東成岩"):
            down_times = tt.get(f"{st}_down", [])
            if not down_times:
                continue
            arr_xfer = up_dep + TRAVEL_MINS[st]
            down_dep = find_next(down_times, arr_xfer + MIN_TRANSFER)
            if down_dep is None:
                continue
            wait = down_dep - arr_xfer
            if wait > 40:
                continue
            arr_dafu   = down_dep + TO_DAFU[st]
            direct_dep = find_next(kame_down, now_min)
            direct_arr = (direct_dep + KAME_DAFU_DIRECT) if direct_dep else None
            results.append({
                "up_dep": up_dep, "xfer_st": st,
                "arr_xfer": arr_xfer, "down_dep": down_dep,
                "wait": wait, "arr_dafu": arr_dafu,
                "direct_dep": direct_dep, "direct_arr": direct_arr,
            })

    seen, deduped = set(), []
    for r in sorted(results, key=lambda x: x["arr_dafu"]):
        key = (r["up_dep"], r["xfer_st"], r["down_dep"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


# ════════════════════════════════════════════════════════════
#  表示
# ════════════════════════════════════════════════════════════

def print_banner(now_min: int, day_type: int, source: str):
    dlbl = {1:"平日", 2:"土曜", 4:"日祝"}.get(day_type, "?")
    bar  = "─" * 56
    print(f"\n{BOLD}{bar}{RST}")
    print(f"{BOLD}  武豊線 抜け道乗換アシスト  {CYN}{fmt(now_min)}{RST}{BOLD} ({dlbl}){RST}")
    print(f"{BOLD}{bar}{RST}")
    print( "  亀崎 ─[武豊方向]→ 途中駅 ─[大府方向]→ 大府")
    print(f"  {GRY}{source}{RST}")
    print(f"{BOLD}{bar}{RST}\n")


def print_route(r: dict, label: str):
    gain = (r["direct_arr"] - r["arr_dafu"]) if r["direct_arr"] else None
    if gain is None:        verdict = ""
    elif gain > 0:          verdict = f"  {GRN}▲ 直通より {gain}分早い{RST}"
    elif gain < 0:          verdict = f"  {YLW}▼ 直通より {abs(gain)}分遅い{RST}"
    else:                   verdict = f"  {GRY}直通と同着{RST}"

    wc = GRN if r["wait"] <= 8 else YLW if r["wait"] <= 18 else RED

    print(f"  {BOLD}[{label}]{RST} "
          f"亀崎 {BLU}{fmt(r['up_dep'])}{RST} 発（武豊方面）"
          f" → {r['xfer_st']} {fmt(r['arr_xfer'])} 着")
    print(f"       待ち {wc}{r['wait']}分{RST}"
          f" → {r['xfer_st']} {GRN}{fmt(r['down_dep'])}{RST} 発（大府方面）"
          f" → 大府 {BOLD}{fmt(r['arr_dafu'])}{RST} 頃着{verdict}")
    if r["direct_dep"]:
        print(f"       {GRY}（直通：亀崎{fmt(r['direct_dep'])}発 → 大府{fmt(r['direct_arr'])}着）{RST}")
    print()


# ════════════════════════════════════════════════════════════
#  main
# ════════════════════════════════════════════════════════════

def get_day_type() -> int:
    wd = date.today().weekday()
    return 2 if wd == 5 else 4 if wd == 6 else 1


def main():
    argv        = sys.argv[1:]
    offline     = "--offline" in argv
    show_source = "--source"  in argv
    argv        = [a for a in argv if not a.startswith("--")]

    if argv:
        try:
            h, m     = map(int, argv[0].split(":"))
            now_min  = h * 60 + m
        except ValueError:
            print("使い方: python3 taketoyo_hayawari.py [HH:MM] [1|2|4] [--offline] [--source]")
            sys.exit(1)
        day_type = int(argv[1]) if len(argv) >= 2 and argv[1] in ("1","2","4") else get_day_type()
    else:
        now      = datetime.now()
        now_min  = now.hour * 60 + now.minute
        day_type = get_day_type()

    tt, source = load_timetables(day_type, offline, show_source)
    print_banner(now_min, day_type, source)

    routes = calc_routes(tt, now_min)

    if not routes:
        print(f"  {YLW}有効な乗換パターンが見つかりませんでした。{RST}")
        nxt = find_next(tt.get("亀崎_down", []), now_min)
        if nxt:
            print(f"  直通：亀崎 {fmt(nxt)} 発 → 大府 {fmt(nxt+KAME_DAFU_DIRECT)} 頃着")
    else:
        print(f"  {BOLD}乗換候補（大府到着が早い順）{RST}\n")
        for r, lbl in zip(routes[:3], LABELS):
            print_route(r, lbl)
        nxt = find_next(tt.get("亀崎_down", []), now_min)
        if nxt:
            print(f"  {GRY}直通（参考）: 亀崎 {fmt(nxt)} 発"
                  f" → 大府 {fmt(nxt+KAME_DAFU_DIRECT)} 頃着{RST}")

    print(f"\n  {GRY}※到着時刻は目安（乙川+28分、半田+25分、東成岩+22分）{RST}")
    print(f"  {GRY}※JR東海PDFが取れなかった場合はYahoo→内蔵の順でフォールバック{RST}\n")


if __name__ == "__main__":
    # for/else が calc_routes の continue/break と相性悪いので修正
    # （Python の for/else は break で else がスキップされる仕様）
    main()
