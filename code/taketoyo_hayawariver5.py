#!/usr/bin/env python3
"""
武豊線 先乗り着席アシスト（2026年ダイヤ）
亀崎 → 武豊方面に先乗り → 乙川/半田/東成岩 で大府行きに乗換

【このスクリプトが出す答え】
  大府到着は直通と同じ（単線なので同じ列車に乗ることになる）。
  価値は「座席を確保しやすいかどうか」。
  → 亀崎で直通を待つより何分早く列車に乗り込めるか を表示する。

【データ取得】
  1. Yahoo!路線情報  transit.yahoo.co.jp（__NEXT_DATA__ JSONをパース）
  2. 内蔵データ      2026年4月ダイヤ・平日（オフライン時 or 取得失敗時）

【使い方】
  python3 taketoyo_hayawari.py              # 現在時刻・自動曜日
  python3 taketoyo_hayawari.py 8:30         # 時刻指定
  python3 taketoyo_hayawari.py 16:00 2      # 時刻+曜日(1=平日 2=土 4=日祝)
  python3 taketoyo_hayawari.py --offline    # 内蔵データのみ（高速・ネット不要）

【必要ライブラリ（初回のみ）】
  pip3 install requests
"""

import sys, re, time, json
from datetime import datetime, date
from typing import Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ── 路線定数 ──────────────────────────────────────────────────
TRAVEL_MINS  = {"乙川": 3, "半田": 6, "東成岩": 9}
MIN_TRANSFER = 1

# ── Yahoo!路線情報 駅ID ───────────────────────────────────────
YAHOO_IDS = {
    "亀崎_up":     ("24890", "1430"),
    "亀崎_down":   ("24890", "1431"),
    "乙川_down":   ("24838", "1431"),
    "半田_down":   ("25107", "1431"),
    "東成岩_down": ("25117", "1431"),
}
YAHOO_BASE    = "https://transit.yahoo.co.jp/timetable/{sid}/{did}"
REQUIRED_KEYS = frozenset(YAHOO_IDS.keys())

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    "Referer": "https://transit.yahoo.co.jp/",
}

# ── 2026年4月 内蔵データ（平日）──────────────────────────────
def _t(p): return sorted(h * 60 + m for h, m in p)

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

# ── カラー ────────────────────────────────────────────────────
RST="\033[0m"; BOLD="\033[1m"
BLU="\033[34m"; GRN="\033[32m"; YLW="\033[33m"
RED="\033[31m"; GRY="\033[90m"; CYN="\033[36m"
LABELS = ["A", "B", "C"]

def fmt(m: int) -> str:
    return f"{m//60}:{m%60:02d}"


# ════════════════════════════════════════════════════════════
#  Yahoo! 取得（__NEXT_DATA__ JSONパース）
# ════════════════════════════════════════════════════════════

def _parse_yahoo(html: str) -> list[int]:
    """
    Yahoo!路線情報は Next.js SPA。
    時刻データは <script id="__NEXT_DATA__"> 内のJSONに入っている。
    構造: props.pageProps.timetableItem.hourTimeTable[].minTimeTable[].minute
    """
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        item = data["props"]["pageProps"]["timetableItem"]
        times = []
        for hour_block in item.get("hourTimeTable", []):
            hour = int(hour_block["hour"])
            for entry in hour_block.get("minTimeTable", []):
                times.append(hour * 60 + int(entry["minute"]))
        return sorted(times)
    except Exception:
        return []


def fetch_yahoo(day_type: int) -> dict[str, list[int]]:
    if not HAS_REQUESTS:
        return {}

    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get("https://transit.yahoo.co.jp/", timeout=10)
        time.sleep(0.3)
    except Exception:
        pass

    result: dict[str, list[int]] = {}
    for key, (sid, did) in YAHOO_IDS.items():
        url = YAHOO_BASE.format(sid=sid, did=did)
        try:
            r = session.get(url, params={"kind": day_type}, timeout=12)
            r.raise_for_status()
            times = _parse_yahoo(r.text)
            if times:
                result[key] = times
                print(f"  {GRY}  {key}: {len(times)}便 ✓{RST}")
            else:
                print(f"  {YLW}  {key}: パース失敗{RST}")
        except Exception as e:
            print(f"  {YLW}  {key}: {e}{RST}")
        time.sleep(0.4)

    return result


# ════════════════════════════════════════════════════════════
#  データ読み込み
# ════════════════════════════════════════════════════════════

def load_timetables(day_type: int, offline: bool
                    ) -> tuple[dict[str, list[int]], str]:
    if offline or not HAS_REQUESTS:
        if not HAS_REQUESTS:
            print(f"  {YLW}requests 未インストール → 内蔵データ使用{RST}")
            print(f"  pip3 install requests")
        if day_type != 1:
            print(f"  {YLW}注意: 内蔵データは平日ダイヤのみです{RST}")
        return BUILTIN, "内蔵データ（2026年4月・平日）"

    print(f"  {GRY}Yahoo!路線情報から取得中...{RST}", flush=True)
    yahoo = fetch_yahoo(day_type)

    # 取得失敗分は内蔵で補完
    merged: dict[str, list[int]] = {}
    for key in REQUIRED_KEYS:
        if yahoo.get(key):
            merged[key] = yahoo[key]
        else:
            merged[key] = BUILTIN.get(key, [])
            if not offline:
                print(f"  {YLW}  {key}: 取得失敗 → 内蔵データで補完{RST}")

    total = sum(len(v) for v in merged.values())
    all_ok = all(yahoo.get(k) for k in REQUIRED_KEYS)
    src = ("Yahoo!路線情報（JR時刻表令和8年3月号）" if all_ok
           else "Yahoo!路線情報 + 内蔵データ（一部補完）")
    print(f"  {GRY}完了（計 {total} 便）{RST}\n")
    return merged, src


# ════════════════════════════════════════════════════════════
#  乗換計算
# ════════════════════════════════════════════════════════════

def find_next(times: list[int], from_min: int) -> Optional[int]:
    for t in times:
        if t >= from_min:
            return t
    return None


def calc_routes(tt: dict[str, list[int]], now_min: int,
                window_min: int = 180) -> list[dict]:
    """
    指標:
      board_advance = 直通亀崎発 − 先乗り亀崎発（何分早く乗れるか）
      wait          = 乗換駅での大府行き待ち時間
      seated_mins   = 亀崎→乗換駅間の確実着席時間
      kame_pass     = 乗換後の列車が亀崎を通過する時刻
    """
    kame_up   = tt.get("亀崎_up",   [])
    kame_down = tt.get("亀崎_down", [])
    results   = []

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

            kame_pass     = down_dep + TRAVEL_MINS[st]
            direct_dep    = find_next(kame_down, now_min)
            board_advance = (direct_dep - up_dep) if direct_dep else None

            results.append({
                "up_dep":        up_dep,
                "xfer_st":       st,
                "arr_xfer":      arr_xfer,
                "down_dep":      down_dep,
                "wait":          wait,
                "seated_mins":   TRAVEL_MINS[st],
                "kame_pass":     kame_pass,
                "direct_dep":    direct_dep,
                "board_advance": board_advance,
            })

    # 早く乗れる順 → 待ち時間短い順
    seen, deduped = set(), []
    for r in sorted(results, key=lambda x: (-(x["board_advance"] or 0), x["wait"])):
        key = (r["up_dep"], r["xfer_st"], r["down_dep"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


# ════════════════════════════════════════════════════════════
#  表示
# ════════════════════════════════════════════════════════════

def print_banner(now_min: int, day_type: int, source: str):
    dlbl = {1: "平日", 2: "土曜", 4: "日祝"}.get(day_type, "?")
    bar  = "─" * 56
    print(f"\n{BOLD}{bar}{RST}")
    print(f"{BOLD}  武豊線 先乗り着席アシスト  {CYN}{fmt(now_min)}{RST}{BOLD} ({dlbl}){RST}")
    print(f"{BOLD}{bar}{RST}")
    print( "  亀崎 ─[武豊方向に先乗り]→ 途中駅 ─[折り返し大府行]→ 大府")
    print(f"  {GRY}{source}{RST}")
    print(f"{BOLD}{bar}{RST}\n")


def print_direct(direct_dep: Optional[int], now_min: int):
    if direct_dep is None:
        print(f"  {GRY}直通大府行: 本日の運行終了{RST}\n")
        return
    wait = direct_dep - now_min
    print(f"  {GRY}◆ 直通で待つ場合: 亀崎 {fmt(direct_dep)} 発（あと {wait} 分待ち）{RST}\n")


def print_route(r: dict, label: str):
    adv  = r["board_advance"]
    wait = r["wait"]

    if adv is None:      adv_str = ""
    elif adv > 0:        adv_str = f"  {GRN}★ {adv}分早く乗れる{RST}"
    elif adv == 0:       adv_str = f"  {GRY}直通と同タイミング{RST}"
    else:                adv_str = f"  {YLW}直通より {abs(adv)}分遅い出発{RST}"

    wc = GRN if wait <= 5 else YLW if wait <= 15 else RED

    print(f"  {BOLD}[{label}]{RST} "
          f"亀崎 {BLU}{fmt(r['up_dep'])}{RST} 発（武豊方面）{adv_str}")
    print(f"       → {r['xfer_st']} {fmt(r['arr_xfer'])} 着"
          f"  待ち {wc}{wait}分{RST}"
          f"  → {r['xfer_st']} {GRN}{fmt(r['down_dep'])}{RST} 発（大府方面）")
    print(f"       この列車の亀崎通過: {fmt(r['kame_pass'])}"
          f"  ／  先乗り着席保証: {GRN}{r['seated_mins']}分{RST}"
          f"（亀崎→{r['xfer_st']}間）")
    if r["direct_dep"]:
        print(f"       {GRY}※大府到着は直通（亀崎{fmt(r['direct_dep'])}発）と同じ{RST}")
    print()


# ════════════════════════════════════════════════════════════
#  main
# ════════════════════════════════════════════════════════════

def get_day_type() -> int:
    wd = date.today().weekday()
    return 2 if wd == 5 else 4 if wd == 6 else 1


def main():
    argv    = sys.argv[1:]
    offline = "--offline" in argv
    argv    = [a for a in argv if not a.startswith("--")]

    if argv:
        try:
            h, m    = map(int, argv[0].split(":"))
            now_min = h * 60 + m
        except ValueError:
            print("使い方: python3 taketoyo_hayawari.py [HH:MM] [1|2|4] [--offline]")
            sys.exit(1)
        day_type = int(argv[1]) if len(argv) >= 2 and argv[1] in ("1","2","4") else get_day_type()
    else:
        now      = datetime.now()
        now_min  = now.hour * 60 + now.minute
        day_type = get_day_type()

    tt, source = load_timetables(day_type, offline)
    print_banner(now_min, day_type, source)

    direct_dep = find_next(tt.get("亀崎_down", []), now_min)
    print_direct(direct_dep, now_min)

    routes = calc_routes(tt, now_min)

    if not routes:
        print(f"  {YLW}有効な先乗りパターンが見つかりませんでした。{RST}\n")
        return

    print(f"  {BOLD}先乗り候補（早く乗れる順）{RST}\n")
    for r, lbl in zip(routes[:3], LABELS):
        print_route(r, lbl)

    print(f"  {GRY}─────────────────────────────────────────────────{RST}")
    print(f"  {GRY}「★ N分早く乗れる」= 直通亀崎発より N分前に乗り込める{RST}")
    print(f"  {GRY}「先乗り着席保証」 = 武豊方面列車で確実に座れる時間{RST}")
    print(f"  {GRY}大府到着時刻は直通と同じ（単線・同一列車のため）{RST}\n")


if __name__ == "__main__":
    main()
