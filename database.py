"""
パチスロデータ DB（SQLite）
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "pachislot.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS daily_records (
            date         TEXT NOT NULL,
            machine_no   INTEGER NOT NULL,
            machine_name TEXT NOT NULL,
            denom        TEXT NOT NULL,
            model_code   TEXT,
            coin_diff    INTEGER,
            bb_count     INTEGER,
            rb_count     INTEGER,
            art_count    INTEGER,
            bb_prob      REAL,
            syn_prob     REAL,
            total_start  INTEGER,
            art_games    INTEGER,
            final_start  INTEGER,
            diff_approx  INTEGER,
            collected_at TEXT,
            PRIMARY KEY (date, machine_no)
        );

        CREATE INDEX IF NOT EXISTS idx_date      ON daily_records(date);
        CREATE INDEX IF NOT EXISTS idx_machine   ON daily_records(machine_no);
        CREATE INDEX IF NOT EXISTS idx_name_date ON daily_records(machine_name, date);
    """)
    # 既存DBへのマイグレーション
    for col_def in [
        "ADD COLUMN model_code  TEXT",
        "ADD COLUMN bb_prob     REAL",
        "ADD COLUMN diff_approx INTEGER",
        "ADD COLUMN first_start INTEGER",
    ]:
        try:
            c.execute(f"ALTER TABLE daily_records {col_def}")
        except Exception:
            pass
    conn.commit()
    conn.close()


def save_records(records: list):
    conn = get_connection()
    c = conn.cursor()
    for r in records:
        c.execute("""
            INSERT OR REPLACE INTO daily_records
            (date, machine_no, machine_name, denom, model_code,
             coin_diff, bb_count, rb_count, art_count,
             bb_prob, syn_prob, total_start, art_games, final_start, collected_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            r["date"], r["machine_no"], r["machine_name"], r["denom"], r.get("model_code"),
            r.get("coin_diff"), r.get("bb_count"), r.get("rb_count"), r.get("art_count"),
            r.get("bb_prob"), r.get("syn_prob"), r.get("total_start"), r.get("art_games"),
            r.get("final_start"), r.get("collected_at"),
        ))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"DB初期化完了: {DB_PATH}")
