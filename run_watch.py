#!/usr/bin/env python3
"""Проверить новые ставки отслеживаемых кошельков. Запуск: python run_watch.py"""
import logging
from src import db, watchlist, report, alerts
from src.api import PolymarketAPI
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

def main():
    wl = watchlist.load_watchlist()
    if not wl:
        print("Список наблюдения пуст. Сначала добавь кошельки:")
        print("  python run_suggest.py --add 15")
        print("  или впиши адреса вручную в watchlist.json")
        return
    conn = db.connect(); api = PolymarketAPI()
    results = watchlist.check_new_activity(conn, api, wl)
    path = report.render_watch(results)
    alerts.send_watch_alert(results)
    total_new = sum(len(r["new"]) for r in results)
    baselined = sum(1 for r in results if r["baseline"])
    print(f"Отслеживается кошельков: {len(wl)}. Новых ставок: {total_new}.")
    if baselined:
        print(f"Впервые в списке (задана точка отсчёта, без алерта): {baselined}.")
    print(f"Отчёт: {path}")
    for r in results:
        if r["new"]:
            who = r["label"] or r["address"][:10]
            print(f"\n  {who} — {len(r['new'])} новых:")
            for a in r["new"][-5:]:
                usd = float(a.get("usdcSize") or 0)
                print(f"    {a.get('side','')} {a.get('outcome','')} ${usd:,.0f} @ {float(a.get('price') or 0):.2f} — {a.get('title','')}")

if __name__ == "__main__":
    main()
