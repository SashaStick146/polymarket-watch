"""Сборщик: качает свежие сделки в базу и подтягивает позиции активных кошельков."""
import time, logging
from . import db
from .api import PolymarketAPI

log = logging.getLogger("collector")

# Фильтр шума: высокочастотные рынки «крипта вверх/вниз за 5 минут» и т.п.
FILTER_NOISE = True
NOISE_MARKERS = ("updown", "up-or-down", "-5m-", "-1h-", "-15m-", "hourly")


def is_noise(trade: dict) -> bool:
    text = f"{(trade.get('slug') or '').lower()} {(trade.get('eventSlug') or '').lower()} {(trade.get('title') or '').lower()}"
    return any(m in text for m in NOISE_MARKERS)


def collect_trades(conn, api, max_pages=40, page_size=500) -> int:
    last_seen_ts = db.get_meta(conn, "last_trade_ts", 0)
    newest_ts = last_seen_ts; total_new = 0
    for page in range(max_pages):
        batch = api.trades(limit=page_size, offset=page * page_size)
        if not batch: break
        clean = [t for t in batch if not (FILTER_NOISE and is_noise(t))]
        new_here = db.insert_trades(conn, clean); total_new += new_here
        batch_min_ts = min(int(t.get("timestamp") or 0) for t in batch)
        newest_ts = max(newest_ts, max(int(t.get("timestamp") or 0) for t in batch))
        log.info("Страница %s: получено %s, новых %s (до ts=%s)", page+1, len(batch), new_here, batch_min_ts)
        if batch_min_ts <= last_seen_ts and new_here == 0:
            log.info("Догнали ранее собранные данные — стоп."); break
    db.set_meta(conn, "last_trade_ts", newest_ts)
    log.info("Готово. Всего новых сделок: %s", total_new); return total_new


def enrich_positions(conn, api, top_n=60, min_volume=200.0) -> int:
    rows = conn.execute(
        """SELECT wallet, SUM(usd) AS vol FROM trades GROUP BY wallet
           HAVING vol >= ? ORDER BY vol DESC LIMIT ?""", (min_volume, top_n)).fetchall()
    now_ts = int(time.time()); enriched = 0
    for r in rows:
        positions = api.positions(r["wallet"], limit=500)
        if positions:
            db.upsert_positions(conn, r["wallet"], positions, now_ts); enriched += 1
            log.info("Позиции кошелька %s… (%s шт.)", r["wallet"][:10], len(positions))
    log.info("Обогащено кошельков: %s", enriched); return enriched
