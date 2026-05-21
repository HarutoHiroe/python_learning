#!/usr/bin/env python3
"""
武豊線 抜け道乗換アシスト
亀崎 → 武豊方面に先乗り → 乙川/半田/東成岩で大府行きに乗換

データソース：Yahoo!路線情報（スクレイピング）
             → 失敗時は内蔵の静的時刻表データにフォールバック

使い方:
  python3 taketoyo_hayawari.py              # 現在時刻・自動曜日判定
  python3 taketoyo_hayawari.py 8:30         # 8:30 から検索（今日の曜日）
  python3 taketoyo_hayawari.py 8:30 2       # 8:30・土曜ダイヤ
  python3 taketoyo_hayawari.py --offline    # 内蔵データのみ使用
"""

import sys
import time
import re
from datetime import datetime, date
from typing import Optional

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ─────────────────────────────────────────────────────────────
# Yahoo!路線情報 駅ID（武豊線）
# ─────────────────────────────────────────────────────────────
STATIONS = {
    "亀崎":   {"id": "24890", "up": "1430", "down": "1431"},
    "乙川":   {"id": "24891", "down": "1431"},
    "半田":   {"id": "25107", "down": "1431"},
    "東成岩": {"id": "25117", "down": "1431"},
}

# 亀崎からの所要時間（分）
TRAVEL_MINS = {"乙川": 3, "半田": 6, "東成岩": 9}

# 各乗換駅から大府までの所要時間（分・目安）
TO_DAFU = {"乙川": 28, "半田": 25, "東成岩": 22}

# 乗換に必要な最低時間
MIN_TRANSFER = 1

BASE_URL = "https://transit.yahoo.co.jp/timetable/{station_id}/{direction}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# ─────────────────────────────────────────────────────────────
# 内蔵静的時刻表（平日）
# Yahoo!路線情報から取得済み。ダイヤ改正で変わる場合あり。
# ─────────────────────────────────────────────────────────────
def _t(pairs):
    return sorted(h * 60 + m for h, m in pairs)

BUILTIN_WEEKDAY = {
    "亀崎_up": _t([  # 武豊方面
        (6,16),(6,30),(6,55),(7,11),(7,33),(7,57),(8,8),(8,33),(9,12),(9,33),
        (10,7),(10,37),(11,7),(11,37),(12,7),(12,37),(13,7),(13,37),(14,7),(14,37),
        (15,7),(15,37),(16,1),(16,24),(16,59),(17,23),(17,53),(18,19),(18,37),
        (19,3),(19,33),(20,5),(20,37),(21,9),(21,40),(22,13),(22,45),(23,15),
    ]),
    "亀崎_down": _t([  # 大府方面
        (5,36),(6,5),(6,38),(6,55),(7,11),(7,33),(7,48),(8,8),(8,33),(8,47),
        (9,12),(9,48),(10,21),(10,51),(11,21),(11,51),(12,21),(12,51),(13,21),(13,51),
        (14,21),(14,51),(15,21),(15,45),(16,15),(16,38),(17,8),(17,37),(18,8),(18,37),
        (19,7),(19,31),(20,6),(20,40),(21,9),(21,45),(22,15),(22,45),(23,15),
    ]),
    "乙川_down": _t([  # 大府方面
        (5,39),(6,8),(6,41),(6,58),(7,14),(7,36),(7,51),(8,11),(8,36),(8,50),
        (9,15),(9,51),(10,24),(10,54),(11,24),(11,54),(12,24),(12,54),(13,24),(13,54),
        (14,24),(14,54),(15,24),(15,48),(16,18),(16,41),(17,11),(17,40),(18,11),(18,40),
        (19,10),(19,34),(20,9),(20,43),(21,12),(21,48),(22,18),(22,48),(23,18),
    ]),
    "半田_down": _t([  # 大府方面
        (5,42),(6,11),(6,44),(7,1),(7,17),(7,39),(7,54),(8,14),(8,39),(8,53),
        (9,18),(9,54),(10,27),(10,57),(11,27),(11,57),(12,27),(12,57),(13,27),(13,57),
        (14,27),(14,57),(15,27),(15,51),(16,21),(16,44),(17,14),(17,43),(18,14),(18,43),
        (19,13),(19,37),(20,12),(20,46),(21,15),(21,51),(22,21),(22,51),(23,21),
    ]),
    "東成岩_down": _t([  # 大府方面
        (5,27),(5,56),(6,27),(6,43),(6,58),(7,18),(7,37),(7,56),(8,21),(8,36),
        (9,3),(9,38),(10,10),(10,40),(11,10),(11,40),(12,10),(12,32),(13,10),(13,40),
        (14,10),(14,40),(15,10),(15,34),(16,3),(16,28),(16,58),(17,28),(17,55),
        (18,22),(18,48),(19,15),(19,43),(20,14),(20,48),(21,17),(21,54),(22,24),(22,54),(23,24),
    ]),
}

# ─────────────────────────────────────────────────────────────
# ターミナルカラー
# ─────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
BLUE   = "\033[34m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
GRAY   = "\033[90m"
CYAN   = "\033[36m"


def fmt(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"


# ─────────────────────────────────────────────────────────────
# スクレイピング
# ─────────────────────────────────────────────────────────────

def fetch_timetable(station_id, direction, day_type, session):
    url = BASE_URL.format(station_id=station_id, direction=direction)
    resp = session.get(url, params={"kind": day_type}, timeout=12)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")
    if not table:
        raise RuntimeError("時刻表テーブルが見つかりません")

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


def scrape_all(day_type):
    if not HAS_REQUESTS:
        return None

    print(f"  {GRAY}Yahoo!路線情報から取得中...{RESET}", flush=True)

    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get("https://transit.yahoo.co.jp/", timeout=10)
        session.headers["Referer"] = "https://transit.yahoo.co.jp/"
        time.sleep(0.5)
    except Exception:
        pass

    targets = [
        ("亀崎_up",     STATIONS["亀崎"]["id"],   STATIONS["亀崎"]["up"]),
        ("亀崎_down",   STATIONS["亀崎"]["id"],   STATIONS["亀崎"]["down"]),
        ("乙川_down",   STATIONS["乙川"]["id"],   STATIONS["乙川"]["down"]),
        ("半田_down",   STATIONS["半田"]["id"],   STATIONS["半田"]["down"]),
        ("東成岩_down", STATIONS["東成岩"]["id"], STATIONS["東成岩"]["down"]),
    ]

    data = {}
    failed = 0
    for key, sid, direction in targets:
        try:
            times = fetch_timetable(sid, direction, day_type, session)
            data[key] = times
            print(f"  {GRAY}  {key}: {len(times)}便 ✓{RESET}")
        except Exception as e:
            print(f"  {YELLOW}  {key}: 失敗 ({e}){RESET}")
            failed += 1
        time.sleep(0.5)

    if failed >= 3:
        print(f"  {YELLOW}取得失敗が多いため内蔵データにフォールバックします。{RESET}")
        return None

    # 一部失敗した場合は内蔵データで補完
    for key, v in BUILTIN_WEEKDAY.items():
        if key not in data:
            data[key] = v

    total = sum(len(v) for v in data.values())
    print(f"  {GRAY}取得完了（計 {total} 便）{RESET}\n")
    return data


# ─────────────────────────────────────────────────────────────
# 乗換計算
# ─────────────────────────────────────────────────────────────

def find_next(times, from_min):
    for t in times:
        if t >= from_min:
            return t
    return None


def calc_routes(timetables, now_min, window_min=120):
    kame_up   = timetables["亀崎_up"]
    kame_down = timetables["亀崎_down"]

    results = []
    for up_dep in kame_up:
        if up_dep < now_min:
            continue
        if up_dep > now_min + window_min:
            break

        for st_name in ("乙川", "半田", "東成岩"):
            down_times = timetables.get(f"{st_name}_down", [])
            if not down_times:
                continue

            arr_xfer = up_dep + TRAVEL_MINS[st_name]
            earliest = arr_xfer + MIN_TRANSFER
            down_dep = find_next(down_times, earliest)

            if down_dep is None:
                continue
            wait = down_dep - arr_xfer
            if wait > 40:
                continue

            arr_dafu   = down_dep + TO_DAFU[st_name]
            direct_dep = find_next(kame_down, now_min)
            direct_arr = (direct_dep + 32) if direct_dep else None

            results.append({
                "up_dep":     up_dep,
                "xfer_st":    st_name,
                "arr_xfer":   arr_xfer,
                "down_dep":   down_dep,
                "wait":       wait,
                "arr_dafu":   arr_dafu,
                "direct_dep": direct_dep,
                "direct_arr": direct_arr,
            })

    seen, deduped = set(), []
    for r in sorted(results, key=lambda x: x["arr_dafu"]):
        key = (r["up_dep"], r["xfer_st"], r["down_dep"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


# ─────────────────────────────────────────────────────────────
# 表示
# ─────────────────────────────────────────────────────────────

def print_header(now_min, day_type, source):
    day_label = {1: "平日", 2: "土曜", 4: "日祝"}.get(day_type, "?")
    bar = "─" * 54
    print()
    print(f"{BOLD}{bar}{RESET}")
    print(f"{BOLD}  武豊線 抜け道乗換アシスト  "
          f"{CYAN}現在 {fmt(now_min)}{RESET}{BOLD} ({day_label}){RESET}")
    print(f"{BOLD}{bar}{RESET}")
    print( "  亀崎 → [武豊方面] → 乙川/半田/東成岩 → [大府方面] → 大府")
    print(f"  {GRAY}データ: {source}{RESET}")
    print(f"{BOLD}{bar}{RESET}")
    print()


def print_route(r, rank):
    direct_arr = r["direct_arr"]
    gain = (direct_arr - r["arr_dafu"]) if direct_arr else None

    if gain and gain > 0:
        gain_str = f"{GREEN}▲ 直通より {gain}分早い{RESET}"
    elif gain and gain < 0:
        gain_str = f"{YELLOW}▼ 直通より {abs(gain)}分遅い{RESET}"
    elif gain == 0:
        gain_str = f"{GRAY}= 直通と同着{RESET}"
    else:
        gain_str = ""

    wait = r["wait"]
    wc = GREEN if wait <= 8 else YELLOW if wait <= 20 else RED

    print(f"  {BOLD}[{rank}]{RESET} "
          f"亀崎 {BLUE}{fmt(r['up_dep'])}{RESET} 発（武豊方面）")
    print(f"       → {r['xfer_st']} {fmt(r['arr_xfer'])} 着  "
          f"（{wc}待ち {wait}分{RESET}）  "
          f"→ {r['xfer_st']} {GREEN}{fmt(r['down_dep'])}{RESET} 発（大府方面）")
    print(f"       → 大府 {BOLD}{fmt(r['arr_dafu'])}{RESET} 頃着  {gain_str}")

    if r["direct_dep"]:
        print(f"       {GRAY}参考：直通→ 亀崎 {fmt(r['direct_dep'])} 発"
              f" → 大府 {fmt(direct_arr)} 着{RESET}")
    print()


# ─────────────────────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────────────────────

def get_day_type():
    wd = date.today().weekday()
    if wd == 5: return 2
    if wd == 6: return 4
    return 1


def main():
    args    = [a for a in sys.argv[1:] if a != "--offline"]
    offline = "--offline" in sys.argv

    if args:
        try:
            h, m = map(int, args[0].split(":"))
            now_min = h * 60 + m
        except ValueError:
            print("使い方: python3 taketoyo_hayawari.py [HH:MM] [1|2|4] [--offline]")
            print("  1=平日（省略可）  2=土曜  4=日祝")
            sys.exit(1)
        day_type = int(args[1]) if len(args) >= 2 and args[1] in ("1","2","4") else get_day_type()
    else:
        now      = datetime.now()
        now_min  = now.hour * 60 + now.minute
        day_type = get_day_type()

    # データ取得
    timetables = None
    source = ""

    if not offline:
        timetables = scrape_all(day_type)
        if timetables:
            source = "Yahoo!路線情報（スクレイピング）"

    if timetables is None:
        if day_type != 1:
            print(f"  {YELLOW}注意: 内蔵データは平日ダイヤです。土日祝は誤差が出る場合があります。{RESET}\n")
        timetables = BUILTIN_WEEKDAY
        source = "内蔵静的データ（2024年ダイヤ・平日）"

    print_header(now_min, day_type, source)

    # 計算・表示
    routes = calc_routes(timetables, now_min, window_min=120)

    if not routes:
        print(f"  {YELLOW}今後2時間以内に有効な乗換パターンが見つかりませんでした。{RESET}")
        nxt = find_next(timetables["亀崎_down"], now_min)
        if nxt:
            print(f"  直通：亀崎 {fmt(nxt)} 発 → 大府 {fmt(nxt+32)} 頃着")
    else:
        print(f"  {BOLD}乗換候補（大府到着が早い順）{RESET}\n")
        for i, r in enumerate(routes[:8], 1):
            print_route(r, i)

        nxt = find_next(timetables["亀崎_down"], now_min)
        if nxt:
            print(f"  {GRAY}直通（参考）：亀崎 {fmt(nxt)} 発 → 大府 {fmt(nxt+32)} 頃着{RESET}")

    print()
    print(f"  {GRAY}※大府到着は目安（乙川+28分、半田+25分、東成岩+22分）{RESET}")
    print(f"  {GRAY}※ダイヤ改正後は --offline を外して再スクレイピングしてください{RESET}")
    print()


if __name__ == "__main__":
    main()
