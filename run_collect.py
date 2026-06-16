#!/usr/bin/env python3
"""Сбор данных. Запуск: python run_collect.py"""
import logging
from src import db, collector
from src.api import PolymarketAPI
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

def main():
    conn = db.connect(); api = PolymarketAPI()
    new_trades = collector.collect_trades(conn, api)
    collector.enrich_positions(conn, api)
    total = conn.execute("SELECT COUNT(*) AS c FROM trades").fetchone()["c"]
    wallets = conn.execute("SELECT COUNT(DISTINCT wallet) AS c FROM trades").fetchone()["c"]
    print(f"Новых сделок за запуск: {new_trades}. Всего в базе: {total} сделок, {wallets} кошельков.")

if __name__ == "__main__":
    main()
