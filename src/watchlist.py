"""
Список наблюдения за кошельками («умные деньги»).
Ведёшь список адресов -> программа показывает их НОВЫЕ ставки с прошлого раза.
Адреса можно добавить вручную в watchlist.json или командой run_suggest.py.

Формат watchlist.json:
{"wallets": [{"address": "0x...", "label": "Кит №1"}]}
"""
import json, logging
from pathlib import Path
from . import db

WATCHLIST_PATH = Path(__file__).resolve().parent.parent / "watchlist.json"
log = logging.getLogger("watchlist")


def load_watchlist(path: Path = WATCHLIST_PATH) -> list:
    if not path.exists(): return []
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("wallets", []) if isinstance(data, dict) else data
    out = []
    for it in items:
        if isinstance(it, str): out.append({"address": it.lower(), "label": ""})
        else: out.append({"address": (it.get("address") or "").lower(), "label": it.get("label") or ""})
    return [w for w in out if w["address"]]


def save_watchlist(wallets: list, path: Path = WATCHLIST_PATH) -> None:
    path.write_text(json.dumps({"wallets": wallets}, ensure_ascii=False, indent=2), encoding="utf-8")


def add_wallets(new_wallets: list, path: Path = WATCHLIST_PATH) -> int:
    existing = load_watchlist(path); have = {w["address"] for w in existing}; added = 0
    for w in new_wallets:
        if w["address"] not in have: existing.append(w); have.add(w["address"]); added += 1
    save_watchlist(existing, path); return added


def suggest_candidates(conn, n: int = 25) -> list:
    base = {r["wallet"]: r for r in conn.execute(
        """SELECT wallet, MAX(pseudonym) AS pseudonym, SUM(usd) AS volume,
                  MAX(usd) AS max_trade, COUNT(*) AS n_trades
           FROM trades GROUP BY wallet""").fetchall()}
    pos = {r["wallet"]: r for r in conn.execute(
        """SELECT wallet, COUNT(*) AS n_resolved,
                  SUM(CASE WHEN realized_pnl>0 THEN 1 ELSE 0 END) AS n_win,
                  SUM(realized_pnl) AS pnl, SUM(initial_value) AS invested
           FROM positions WHERE redeemable=1 GROUP BY wallet""").fetchall()}
    c = []
    for wallet, b in base.items():
        p = pos.get(wallet); pnl = (p["pnl"] if p else 0) or 0
        nres = (p["n_resolved"] if p else 0) or 0; invested = (p["invested"] if p else 0) or 0
        wr = (p["n_win"] / nres) if (p and nres) else None
        roi = (pnl / invested) if invested > 0 else None
        c.append({"address": wallet, "pseudonym": b["pseudonym"] or "",
            "volume": round(b["volume"] or 0, 2), "max_trade": round(b["max_trade"] or 0, 2),
            "pnl": round(pnl, 2), "roi": roi, "winrate": wr, "n_resolved": nres})
    c.sort(key=lambda x: (-(x["pnl"]), -(x["volume"])))
    return c[:n]


def check_new_activity(conn, api, wallets: list, per_wallet_limit: int = 100) -> list:
    results = []
    for w in wallets:
        addr = w["address"]; key = f"watch_last_ts:{addr}"
        last = db.get_meta(conn, key, None)
        acts = api.activity(addr, limit=per_wallet_limit) or []
        trades = [a for a in acts if a.get("type") == "TRADE"]
        if last is None:
            latest = max((int(a.get("timestamp") or 0) for a in trades), default=0)
            db.set_meta(conn, key, latest)
            results.append({"address": addr, "label": w["label"], "new": [], "baseline": True}); continue
        new = [a for a in trades if int(a.get("timestamp") or 0) > last]
        new.sort(key=lambda a: int(a.get("timestamp") or 0))
        if new: db.set_meta(conn, key, max(int(a.get("timestamp") or 0) for a in new))
        results.append({"address": addr, "label": w["label"], "new": new, "baseline": False})
    return results
