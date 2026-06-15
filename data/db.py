import sqlite3
import json
import os

DB_PATH = "data/odds.db"


def init_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at  TEXT NOT NULL,
            event_id    TEXT NOT NULL,
            home_team   TEXT NOT NULL,
            away_team   TEXT NOT NULL,
            commence    TEXT NOT NULL,
            bookmaker   TEXT NOT NULL,
            home_odds   REAL,
            draw_odds   REAL,
            away_odds   REAL
        );

        CREATE TABLE IF NOT EXISTS arb_opportunities (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at  TEXT NOT NULL,
            event_id     TEXT NOT NULL,
            match        TEXT NOT NULL,
            commence     TEXT NOT NULL,
            margin       REAL NOT NULL,
            profit_pct   REAL NOT NULL,
            detail_json  TEXT NOT NULL,
            status       TEXT DEFAULT 'open'
        );

        CREATE INDEX IF NOT EXISTS idx_odds_event ON odds_snapshots(event_id, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_arb_detected ON arb_opportunities(detected_at);
    """)
    conn.commit()
    conn.close()


def save_odds(fetched_at: str, events: list):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for event in events:
        for bm_name, odds in event.get("bookmakers", {}).items():
            c.execute("""
                INSERT INTO odds_snapshots
                    (fetched_at, event_id, home_team, away_team, commence, bookmaker, home_odds, draw_odds, away_odds)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                fetched_at,
                event["id"],
                event["home_team"],
                event["away_team"],
                event["commence"],
                bm_name,
                odds.get("home"),
                odds.get("draw"),
                odds.get("away"),
            ))
    conn.commit()
    conn.close()


def save_arb(detected_at, event_id, match, commence, margin, profit_pct, detail):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO arb_opportunities
            (detected_at, event_id, match, commence, margin, profit_pct, detail_json)
        VALUES (?,?,?,?,?,?,?)
    """, (detected_at, event_id, match, commence, margin, profit_pct, json.dumps(detail, ensure_ascii=False)))
    conn.commit()
    conn.close()


def get_recent_arbs(limit=50):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if limit is None:
        rows = c.execute("""
            SELECT * FROM arb_opportunities ORDER BY detected_at DESC
        """).fetchall()
    else:
        rows = c.execute("""
            SELECT * FROM arb_opportunities ORDER BY detected_at DESC LIMIT ?
        """, (limit,)).fetchall()
    conn.close()
    records = []
    for row in rows:
        record = dict(row)
        try:
            record["detail"] = json.loads(record.get("detail_json") or "{}")
        except json.JSONDecodeError:
            record["detail"] = {}
        records.append(record)
    return records


if __name__ == "__main__":
    init_db()
    print("数据库初始化完成:", DB_PATH)
