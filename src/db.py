"""
База данных (SQLite). Хранит сделки, позиции кошельков и служебные пометки.
SQLite — это просто файл на диске, отдельный сервер не нужен.
"""
import os, sqlite3, hashlib, json
from pathlib import Path

DB_PATH = Path(os.getenv("POLY_DB",
              Path(__file__).resolve().parent.parent / "data" / "polymarket.db"))


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    _init_schema(conn); return conn


def _init_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY, wallet TEXT, pseudonym TEXT, name TEXT,
            side TEXT, asset TEXT, condition_id TEXT, outcome TEXT,
            outcome_index INTEGER, size REAL, price REAL, usd REAL, ts INTEGER,
            title TEXT, slug TEXT, tx_hash TEXT);
        CREATE INDEX IF NOT EXISTS idx_trades_wallet ON trades(wallet);
        CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(condition_id);
        CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);
        CREATE TABLE IF NOT EXISTS positions (
            wallet TEXT, condition_id TEXT, asset TEXT, title TEXT, outcome TEXT,
            avg_price REAL, size REAL, initial_value REAL, current_value REAL,
            realized_pnl REAL, cash_pnl REAL, percent_pnl REAL, redeemable INTEGER,
            end_date TEXT, updated_ts INTEGER, PRIMARY KEY (wallet, asset));
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        """)
    conn.commit()


def trade_id(t: dict) -> str:
    raw = (f"{t.get('transactionHash')}|{t.get('asset')}|{t.get('proxyWallet')}|"
           f"{t.get('side')}|{t.get('size')}|{t.get('price')}|{t.get('timestamp')}")
    return hashlib.sha1(raw.encode()).hexdigest()


def insert_trades(conn, trades: list) -> int:
    rows = []
    for t in trades:
        size = float(t.get("size") or 0); price = float(t.get("price") or 0)
        rows.append((trade_id(t), (t.get("proxyWallet") or "").lower(),
            t.get("pseudonym") or "", t.get("name") or "", t.get("side") or "",
            t.get("asset") or "", t.get("conditionId") or "", t.get("outcome") or "",
            t.get("outcomeIndex"), size, price, round(size*price, 4),
            int(t.get("timestamp") or 0), t.get("title") or "", t.get("slug") or "",
            t.get("transactionHash") or ""))
    before = conn.total_changes
    conn.executemany(
        """INSERT OR IGNORE INTO trades
           (id, wallet, pseudonym, name, side, asset, condition_id, outcome,
            outcome_index, size, price, usd, ts, title, slug, tx_hash)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.commit(); return conn.total_changes - before


def upsert_positions(conn, wallet: str, positions: list, now_ts: int) -> None:
    rows = []
    for p in positions:
        rows.append((wallet.lower(), p.get("conditionId") or "", p.get("asset") or "",
            p.get("title") or "", p.get("outcome") or "", float(p.get("avgPrice") or 0),
            float(p.get("size") or 0), float(p.get("initialValue") or 0),
            float(p.get("currentValue") or 0), float(p.get("realizedPnl") or 0),
            float(p.get("cashPnl") or 0), float(p.get("percentPnl") or 0),
            1 if p.get("redeemable") else 0, p.get("endDate") or "", now_ts))
    conn.executemany(
        """INSERT OR REPLACE INTO positions
           (wallet, condition_id, asset, title, outcome, avg_price, size,
            initial_value, current_value, realized_pnl, cash_pnl, percent_pnl,
            redeemable, end_date, updated_ts)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.commit()


def get_meta(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_meta(conn, key: str, value) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                 (key, json.dumps(value))); conn.commit()
