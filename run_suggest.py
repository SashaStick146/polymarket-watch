#!/usr/bin/env python3
"""
Подсказать кандидатов в список наблюдения и (по желанию) добавить их.
  python run_suggest.py            # показать топ-25
  python run_suggest.py --add 15   # показать и добавить топ-15 в watchlist.json
  python run_suggest.py --add 15 --min-pnl 1000
"""
import sys, logging
from src import db, watchlist
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

def main():
    args = sys.argv[1:]; add_n = 0; min_pnl = None
    if "--add" in args:
        i = args.index("--add"); add_n = int(args[i+1]) if i+1 < len(args) else 15
    if "--min-pnl" in args:
        i = args.index("--min-pnl"); min_pnl = float(args[i+1]) if i+1 < len(args) else 0.0
    conn = db.connect()
    cands = watchlist.suggest_candidates(conn, n=max(add_n, 25))
    if min_pnl is not None: cands = [c for c in cands if c["pnl"] >= min_pnl]
    print(f"\n{'PnL':>12}  {'Оборот':>12}  {'Винрейт':>8}  Аккаунт / адрес")
    print("-" * 80)
    for c in cands:
        wr = f"{c['winrate']:.0%}" if c["winrate"] is not None else "—"
        print(f"${c['pnl']:>11,.0f}  ${c['volume']:>11,.0f}  {wr:>8}  {(c['pseudonym'] or '—')[:18]:<18} {c['address']}")
    if add_n > 0:
        to_add = [{"address": c["address"], "label": (c["pseudonym"] or "smart")[:24] + f" (PnL ${c['pnl']:,.0f})"} for c in cands[:add_n]]
        added = watchlist.add_wallets(to_add)
        print(f"\nДобавлено в watchlist.json: {added} (всего в списке: {len(watchlist.load_watchlist())}).")
    else:
        print("\nЧтобы добавить топ в список: python run_suggest.py --add 15")

if __name__ == "__main__":
    main()
