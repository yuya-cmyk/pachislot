"""
papimo.jp スクレイパー（オリエンタルパサージュ自由が丘店）
"""
import re
import time
import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

JST = ZoneInfo("Asia/Tokyo")
STORE_CODE = "00031501"
BASE_URL = f"https://papimo.jp/h/{STORE_CODE}/hit"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
REQUEST_DELAY = 1.2   # リクエスト間隔（秒）
HARD_TIMEOUT  = 60    # スレッドレベルの上限（秒）
MAX_RETRY     = 3

# select option value → フィールド名
SORT_TYPES = {
    "coin_diff":   0,   # 出メダル（ボーナス払い出し合計）
    "bb_count":    1,   # BB回数
    "rb_count":    2,   # RB回数
    "art_count":   3,   # ART回数
    "bb_prob":     4,   # BB確率（1/N 形式）
    "syn_prob":    5,   # 合成確率（1/N 形式）
    "total_start": 6,   # 総スタート（総回転数）
    "art_games":   7,   # ARTゲーム数
    "final_start": 8,   # 最終スタート（最終回転数）
}

SLUMP_BASE = "https://papimo.jp/h/slp"
# スランプグラフ画像のスケール: 5000枚 = 72px（1メジャー目盛り）
_SLUMP_MEDALS_PER_PX = 5000 / 72
_SLUMP_GRAPH_LINE_COLOR = (236, 34, 52)   # 赤（グラフ線）
_SLUMP_AXIS_COLOR       = (52,  50, 52)   # 黒（ゼロ軸）

DENOMS = {"S20": "21.73", "S5": "5"}


# ── HTTP リクエスト ────────────────────────────────────────────────────────────

def _get(url: str) -> requests.Response:
    """threading ベース hard timeout 付きリクエスト（D-state 対策）"""
    result_box = [None, None]

    def _do():
        try:
            with requests.Session() as s:
                s.headers.update(HEADERS)
                r = s.get(url, timeout=(30, 45))
            result_box[0] = r
        except Exception as e:
            result_box[1] = e

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=HARD_TIMEOUT)

    if t.is_alive():
        raise TimeoutError(f"HTTP GET timed out ({HARD_TIMEOUT}s): {url}")
    if result_box[1]:
        raise result_box[1]
    result_box[0].raise_for_status()
    return result_box[0]


def _get_with_retry(url: str, ajax: bool = False) -> requests.Response:
    extra_headers = {"X-Requested-With": "XMLHttpRequest"} if ajax else {}
    for i in range(MAX_RETRY):
        try:
            result_box = [None, None]
            def _do():
                try:
                    with requests.Session() as s:
                        s.headers.update({**HEADERS, **extra_headers})
                        r = s.get(url, timeout=(30, 45))
                    result_box[0] = r
                except Exception as e:
                    result_box[1] = e
            t = threading.Thread(target=_do, daemon=True)
            t.start()
            t.join(timeout=HARD_TIMEOUT)
            if t.is_alive():
                raise TimeoutError(f"HTTP GET timed out ({HARD_TIMEOUT}s): {url}")
            if result_box[1]:
                raise result_box[1]
            result_box[0].raise_for_status()
            return result_box[0]
        except Exception as e:
            if i == MAX_RETRY - 1:
                raise
            wait = 10 * (i + 1)
            logging.warning("取得失敗（%d/%d）%s: %s → %d秒後リトライ", i+1, MAX_RETRY, url, e, wait)
            time.sleep(wait)


# ── データ取得 ────────────────────────────────────────────────────────────────

def get_denom_ids() -> dict:
    """トップページから当日の S20/S5 ID を動的に取得"""
    r = _get_with_retry(f"{BASE_URL}/top/")
    soup = BeautifulSoup(r.content, "html.parser")

    ids = {}
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        m20 = re.search(r"index_machine/1-21\.73-(\d+)/", href)
        if m20:
            ids["S20"] = m20.group(1)
        m5 = re.search(r"index_machine/1-5-(\d+)/", href)
        if m5:
            ids["S5"] = m5.group(1)

    return ids


def _parse_machine_items(soup, denom_code: str, denom_id: str, machines: list, seen: set):
    """soup から機種リストを抽出して machines に追記（重複除去あり）"""
    pattern = rf"index_sort/(\d+)/1-{re.escape(denom_code)}-{denom_id}"
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        m = re.search(pattern, href)
        if not m:
            continue
        code = m.group(1)
        if code in seen:
            continue
        seen.add(code)

        name_el = a.find("p", class_="name")
        if not name_el:
            continue

        # 台数を <span class="count"> から抽出し、名前から除去
        count_span = name_el.find("span", class_="count")
        count = 0
        if count_span:
            cm = re.search(r"(\d+)", count_span.get_text())
            if cm:
                count = int(cm.group(1))
            count_span.extract()
        name = name_el.get_text(strip=True)
        machines.append({"code": code, "name": name, "count": count})


def get_machine_list(denom_key: str, denom_id: str) -> list:
    """
    機種一覧を全ページ取得（「もっと見る」ページネーション対応）
    → [{"code": str, "name": str, "count": int}]
    """
    denom_code = DENOMS[denom_key]
    base_url  = f"{BASE_URL}/index_machine/1-{denom_code}-{denom_id}/"
    ajax_base = f"https://papimo.jp/h/{STORE_CODE}/hit/index-machine/1-{denom_code}-{denom_id}"

    machines: list = []
    seen: set = set()

    # ページ1（初期HTML）
    r = _get_with_retry(base_url)
    time.sleep(REQUEST_DELAY)
    soup = BeautifulSoup(r.content, "html.parser")
    _parse_machine_items(soup, denom_code, denom_id, machines, seen)

    # max_page を取得
    max_page_el = soup.find("input", {"id": "max_page"})
    max_page = int(max_page_el.get("value", 1)) if max_page_el else 1
    logging.info("  %s max_page=%d", denom_key, max_page)

    # ページ2以降（AJAXエンドポイント: index-machine ハイフン区切り）
    for page in range(2, max_page + 1):
        url = f"{ajax_base}?page={page}"
        r = _get_with_retry(url, ajax=True)
        time.sleep(REQUEST_DELAY)
        soup = BeautifulSoup(r.content, "html.parser")
        before = len(machines)
        _parse_machine_items(soup, denom_code, denom_id, machines, seen)
        logging.info("  %s page=%d/%d +%d機種（累計%d）",
                     denom_key, page, max_page, len(machines) - before, len(machines))

    return machines


def _parse_value(text: str, field: str):
    """セルのテキストを数値に変換（合成確率は 1/N の分母を返す）"""
    text = text.strip().replace(",", "")
    if not text or text in ("-", "－"):
        return None

    if field in ("syn_prob", "bb_prob"):
        # "1/124" → 124.0
        m = re.search(r"1/([0-9.]+)", text)
        if m:
            return float(m.group(1))
        return None

    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return None


def get_table_data(machine_code: str, denom_key: str, denom_id: str,
                   sort_type: int, field: str, date_offset: int = 0) -> dict:
    """
    sort_type のデータテーブルを取得
    date_offset: 0=当日, 1=1日前, 2=2日前
    戻り値: {machine_no (int): value}
    """
    denom_code = DENOMS[denom_key]
    url = (f"{BASE_URL}/index_sort/{machine_code}"
           f"/1-{denom_code}-{denom_id}/{sort_type}/{date_offset}/0/0")

    r = _get_with_retry(url)
    time.sleep(REQUEST_DELAY)
    soup = BeautifulSoup(r.content, "html.parser")

    table = soup.find("table", id="table-sort")
    if not table:
        return {}
    tbody = table.find("tbody")
    if not tbody:
        return {}

    data = {}
    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        # 台番号: "0870空き" → 870
        raw = cells[0].get_text(strip=True)
        no_m = re.search(r"\d+", raw)
        if not no_m:
            continue
        machine_no = int(no_m.group())

        # 当日の値（cells[1]）
        val = _parse_value(cells[1].get_text(strip=True), field)
        if val is not None:
            data[machine_no] = val

    return data


# ── メイン収集処理 ────────────────────────────────────────────────────────────

def collect_store_data(target_date: str, date_offset: int = 0) -> list:
    """
    全機種のデータを収集してレコードリストを返す
    target_date: YYYYMMDD
    date_offset: 0=当日, 1=前日, 2=2日前
    """
    collected_at = datetime.now(JST).isoformat()

    logging.info("=== 収集開始 date=%s offset=%d ===", target_date, date_offset)
    denom_ids = get_denom_ids()
    if not denom_ids:
        raise ValueError("denomination ID の取得に失敗しました")
    logging.info("denom_ids: %s", denom_ids)
    time.sleep(REQUEST_DELAY)

    all_records = []

    for denom_key in ["S20", "S5"]:
        if denom_key not in denom_ids:
            logging.warning("%s のIDが見つかりません、スキップ", denom_key)
            continue

        denom_id = denom_ids[denom_key]
        logging.info("[%s] 機種一覧取得中 (ID=%s)...", denom_key, denom_id)

        try:
            machines = get_machine_list(denom_key, denom_id)
        except Exception as e:
            logging.error("[%s] 機種一覧取得失敗: %s", denom_key, e)
            continue

        logging.info("[%s] %d 機種", denom_key, len(machines))

        for machine in machines:
            code = machine["code"]
            name = machine["name"]
            logging.info("  [%s] %s...", denom_key, name)

            # 台ごとのデータを集約
            machine_data = {}  # {machine_no: {field: value}}

            for field, sort_type in SORT_TYPES.items():
                try:
                    vals = get_table_data(code, denom_key, denom_id,
                                          sort_type, field, date_offset)
                    for mno, v in vals.items():
                        machine_data.setdefault(mno, {})[field] = v
                except Exception as e:
                    logging.warning("    %s sort_type=%d 失敗: %s", name, sort_type, e)

            for machine_no, fields in machine_data.items():
                all_records.append({
                    "date":         target_date,
                    "machine_no":   machine_no,
                    "machine_name": name,
                    "denom":        denom_key,
                    "model_code":   code,
                    "coin_diff":    fields.get("coin_diff"),
                    "bb_count":     fields.get("bb_count"),
                    "rb_count":     fields.get("rb_count"),
                    "art_count":    fields.get("art_count"),
                    "bb_prob":      fields.get("bb_prob"),
                    "syn_prob":     fields.get("syn_prob"),
                    "total_start":  fields.get("total_start"),
                    "art_games":    fields.get("art_games"),
                    "final_start":  fields.get("final_start"),
                    "collected_at": collected_at,
                })

    logging.info("=== 収集完了: %d 件 ===", len(all_records))
    return all_records


# ── スランプグラフ解析 ────────────────────────────────────────────────────────

def _get_slump_suffix(machine_no: int) -> str:
    """1台のview ページからスランプ画像URLのサフィックス（p1/p2/p3 形式）を取得する。"""
    try:
        r = _get_with_retry(f"{BASE_URL}/view/{machine_no}")
        soup = BeautifulSoup(r.content, "html.parser")
        el = soup.find(id="tab-graph-today")
        if el:
            img = el.find("img")
            if img and img.get("src"):
                # /h/slp/{store}/{mno}/{model}/{date}/{p1}/{p2}/{p3}.png
                parts = img["src"].replace(".png", "").split("/")
                suffix = "/".join(parts[-3:])
                if suffix:
                    return suffix
    except Exception as e:
        logging.warning("slump suffix 取得失敗 machine=%d: %s", machine_no, e)
    return "43/11/18"


def _analyze_slump_image(img_bytes: bytes) -> int | None:
    """
    スランプグラフPNGを解析し推定差枚数（500枚単位）を返す。
    グラフ線（赤）の最終X位置のY座標とゼロ軸の差をスケール変換。
    """
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        w, h = img.size
        pix = img.load()

        # ゼロ軸 = 暗いピクセルが最も多い水平行（y=150〜420の範囲で探索）
        zero_y = max(
            range(150, min(420, h)),
            key=lambda y: sum(1 for x in range(30, w - 10) if pix[x, y] == _SLUMP_AXIS_COLOR)
        )

        # 赤いグラフ線ピクセルを収集
        red_px = [(x, y) for x in range(w) for y in range(h)
                  if pix[x, y] == _SLUMP_GRAPH_LINE_COLOR]
        if not red_px:
            return 0

        # 最右端5px以内のY座標の平均
        max_x = max(x for x, y in red_px)
        final_ys = [y for x, y in red_px if x >= max_x - 5]
        avg_y = sum(final_ys) / len(final_ys)

        # ゼロより上 = プラス, 下 = マイナス
        dist_px = zero_y - avg_y
        diff = dist_px * _SLUMP_MEDALS_PER_PX

        # 500枚単位に丸める
        return int(round(diff / 500) * 500)
    except Exception as e:
        logging.debug("slump image 解析エラー: %s", e)
        return None


def _fetch_first_start(machine_no: int) -> int | None:
    """viewページの大当たり履歴から当日初当たりゲーム数を取得する。"""
    try:
        # 405（レートリミット）はリトライ不要のため直接リクエスト
        r = requests.get(f"{BASE_URL}/view/{machine_no}", headers=HEADERS, timeout=20)
        if r.status_code != 200:
            logging.debug("first_start HTTP %d: machine=%d", r.status_code, machine_no)
            return None
        soup = BeautifulSoup(r.content, "html.parser")
        hist = soup.find("table", class_="history")
        if not hist:
            return None
        rows = hist.find_all("tr")
        if len(rows) < 2:
            return None
        # 最後の行 = 当日最初のボーナス
        last_row = rows[-1].find_all("td")
        if len(last_row) < 3:
            return None
        val = last_row[2].get_text(strip=True).replace(",", "")
        return int(val) if val.isdigit() else None
    except Exception as e:
        logging.debug("first_start 取得失敗 machine=%d: %s", machine_no, e)
        return None


def collect_first_starts(target_date: str) -> int:
    """
    全台のviewページから初当たりゲーム数を並列取得してDBを更新する。
    target_date: YYYYMMDD
    """
    from database import get_connection

    conn = get_connection()
    rows = conn.execute(
        "SELECT machine_no FROM daily_records WHERE date=? ORDER BY machine_no",
        (target_date,)
    ).fetchall()
    conn.close()

    if not rows:
        logging.warning("first_start: %s のレコードが見つかりません", target_date)
        return 0

    results: dict[int, int | None] = {}
    semaphore = threading.Semaphore(5)

    def _fetch_one(machine_no: int):
        with semaphore:
            results[machine_no] = _fetch_first_start(machine_no)

    threads = [
        threading.Thread(target=_fetch_one, args=(row["machine_no"],), daemon=True)
        for row in rows
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    conn = get_connection()
    updated = sum(
        conn.execute(
            "UPDATE daily_records SET first_start=? WHERE date=? AND machine_no=?",
            (val, target_date, mno)
        ).rowcount
        for mno, val in results.items()
        if val is not None
    )
    conn.commit()
    conn.close()

    logging.info("first_start: %d/%d 台を更新", updated, len(rows))
    return updated


def collect_slump_diffs(target_date: str) -> int:
    """
    全機種のスランプグラフを並列取得・解析してDBの diff_approx を更新する。
    target_date: YYYYMMDD
    """
    from database import get_connection

    conn = get_connection()
    rows = conn.execute(
        "SELECT machine_no, model_code FROM daily_records "
        "WHERE date=? AND model_code IS NOT NULL ORDER BY machine_no",
        (target_date,)
    ).fetchall()
    conn.close()

    if not rows:
        logging.warning("slump: %s の model_code 付きレコードが見つかりません", target_date)
        return 0

    # 1台からサフィックスを取得
    suffix = _get_slump_suffix(rows[0]["machine_no"])
    logging.info("slump suffix=%s (%d台処理)", suffix, len(rows))
    time.sleep(REQUEST_DELAY)

    results: dict[int, int | None] = {}
    semaphore = threading.Semaphore(10)  # 同時10接続

    def _fetch_one(machine_no: int, model_code: str):
        url = f"{SLUMP_BASE}/{STORE_CODE}/{machine_no}/{model_code}/{target_date}/{suffix}.png"
        with semaphore:
            try:
                r = requests.get(url, headers=HEADERS, timeout=15)
                if r.status_code == 200:
                    results[machine_no] = _analyze_slump_image(r.content)
                else:
                    logging.debug("slump HTTP %d: machine=%d url=%s", r.status_code, machine_no, url)
            except Exception as e:
                logging.debug("slump fetch error machine=%d: %s", machine_no, e)

    threads = [
        threading.Thread(target=_fetch_one, args=(row["machine_no"], row["model_code"]), daemon=True)
        for row in rows
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    # DB更新
    conn = get_connection()
    updated = sum(
        conn.execute(
            "UPDATE daily_records SET diff_approx=? WHERE date=? AND machine_no=?",
            (diff, target_date, mno)
        ).rowcount
        for mno, diff in results.items()
        if diff is not None
    )
    conn.commit()
    conn.close()

    logging.info("slump: %d/%d 台を更新", updated, len(rows))
    return updated
