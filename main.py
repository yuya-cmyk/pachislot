#!/usr/bin/env python3
"""
パチスロデータ 日次収集・HTML生成メインスクリプト
22:50 launchd から実行。24:00 までに終了（watchdog付き）。
"""
import argparse
import logging
import os
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
from database import init_db, save_records
from scraper import collect_store_data, collect_slump_diffs, collect_first_starts
from generate_html import generate_daily_html, generate_stats_html, update_latest

JST       = ZoneInfo("Asia/Tokyo")
LOG_FILE  = Path(__file__).parent / "logs" / "collect.log"

# watchdog: 22:50 開始として最大80分 = 24:10 前に終了
_TIMEOUT_SEC = 80 * 60
_deadline    = time.time() + _TIMEOUT_SEC


def _watchdog():
    while True:
        time.sleep(30)
        if time.time() >= _deadline:
            print(f"【タイムアウト】{_TIMEOUT_SEC//60}分を超えたため強制終了します", flush=True)
            os._exit(2)

threading.Thread(target=_watchdog, daemon=True).start()


def setup_logging():
    LOG_FILE.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # コンソールにも出力
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    logging.getLogger().addHandler(console)


def main():
    setup_logging()
    init_db()

    parser = argparse.ArgumentParser()
    parser.add_argument("--date",   type=str, default=None,
                        help="対象日 YYYYMMDD（省略時: 当日）")
    parser.add_argument("--offset", type=int, default=0,
                        help="日付オフセット: 0=当日, 1=前日, 2=2日前")
    parser.add_argument("--no-html", action="store_true",
                        help="HTML生成をスキップ")
    args = parser.parse_args()

    # 対象日の決定
    if args.date:
        target_date = args.date
        date_offset = args.offset
    else:
        # デフォルト: 当日（22:50 = 閉店後のデータ）
        target_date = date.today().strftime("%Y%m%d")
        date_offset = args.offset

    logging.info("==== pachislot-collector start ==== date=%s offset=%d",
                 target_date, date_offset)

    try:
        # 収集
        records = collect_store_data(target_date, date_offset)

        if not records:
            logging.warning("収集レコードが 0 件でした")
            sys.exit(1)

        # DB 保存
        save_records(records)
        logging.info("DB保存完了: %d 件", len(records))

        # スランプグラフから推定差枚数を取得
        slump_updated = collect_slump_diffs(target_date)
        logging.info("スランプ解析完了: %d 台", slump_updated)

        first_updated = collect_first_starts(target_date)
        logging.info("初当たり取得完了: %d 台", first_updated)

        # HTML 生成
        if not args.no_html:
            daily_path = generate_daily_html(target_date)
            logging.info("日次HTML: %s", daily_path)

            stats_path = generate_stats_html()
            logging.info("統計HTML: %s", stats_path)

            update_latest(target_date)
            logging.info("latest.html 更新")

        logging.info("==== 完了 exit=0 ====")

    except Exception as e:
        logging.error("FATAL: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
