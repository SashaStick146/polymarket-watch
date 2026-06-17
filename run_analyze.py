#!/usr/bin/env python3
"""Анализ + отчёт. Запуск: python run_analyze.py"""
import logging
from src import db, analyze, report, alerts
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

def main():
    conn = db.connect()
    results, cluster_pairs = analyze.score_wallets(conn)
    path = report.render(results, cluster_pairs)
    alerts.send_alert(results, threshold=30)
    print(f"Проанализировано кошельков: {len(results)}")
    print(f"Отчёт сохранён: {path}")
    print("\nТоп-10 по баллу подозрительности:")
    for r in results[:10]:
        pseudo = r.get("pseudonym") or r["wallet"][:10]
        reasons = "; ".join(r["reasons"][:2]) or "—"
        print(f"  {r['score']:5.1f}  {pseudo:<18}  {reasons}")

if __name__ == "__main__":
    main()
