#!/usr/bin/env python3
"""Анализ + отчёт + журнал помеченных + Telegram только про новых."""
import os
import time
import html
import logging
from pathlib import Path

from src import db, analyze, report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

THRESHOLD = 30  # с какого балла аккаунт считается «помеченным»
FLAGGED_REPORT = Path(__file__).resolve().parent / "flagged_report.html"


def ensure_flagged_table(conn):
    conn.executescript(
        """CREATE TABLE IF NOT EXISTS flagged (
            wallet TEXT PRIMARY KEY, pseudonym TEXT,
            first_ts INTEGER, first_score REAL, first_winrate REAL, first_pnl REAL,
            last_ts INTEGER, last_score REAL, last_winrate REAL, last_pnl REAL,
            reasons TEXT)"""
    )
    conn.commit()


def telegram(text):
    token = os.getenv("TELEGRAM_TOKEN"); chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        logging.info("Telegram не настроен — пропускаю алерт.")
        return
    import requests
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat, "text": text, "disable_web_page_preview": "true"}, timeout=30)
        logging.info("Алерт отправлен.")
    except requests.RequestException as e:
        logging.warning("Не удалось отправить алерт: %s", e)


def _wr(v):
    return f"{v:.0%}" if isinstance(v, (int, float)) else "н/д"


def _pnl(v):
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "—"


def update_flagged(conn, results, now):
    new_items = []
    for r in results:
        if r["score"] < THRESHOLD:
            continue
        wr = r.get("pos_winrate"); pnl = r.get("pos_pnl")
        reasons = "; ".join(r["reasons"])
        row = conn.execute("SELECT wallet FROM flagged WHERE wallet=?", (r["wallet"],)).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO flagged (wallet, pseudonym, first_ts, first_score,
                   first_winrate, first_pnl, last_ts, last_score, last_winrate,
                   last_pnl, reasons) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (r["wallet"], r.get("pseudonym") or "", now, r["score"], wr, pnl,
                 now, r["score"], wr, pnl, reasons))
            new_items.append(r)
        else:
            conn.execute(
                """UPDATE flagged SET last_ts=?, last_score=?, last_winrate=?,
                   last_pnl=?, pseudonym=?, reasons=? WHERE wallet=?""",
                (now, r["score"], wr, pnl, r.get("pseudonym") or "", reasons, r["wallet"]))
    conn.commit()
    return new_items


def render_flagged(conn, out_path=FLAGGED_REPORT):
    rows = conn.execute("SELECT * FROM flagged ORDER BY last_ts DESC").fetchall()
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    trs = []
    for r in rows:
        wallet = r["wallet"]; link = f"https://polymarket.com/profile/{wallet}"
        pseudo = html.escape(r["pseudonym"] or (wallet[:6] + "…" + wallet[-4:]))
        flagged_date = time.strftime("%Y-%m-%d", time.gmtime(int(r["first_ts"] or 0)))
        wr_cell = f"{_wr(r['first_winrate'])} → {_wr(r['last_winrate'])}"
        pnl_cell = f"{_pnl(r['first_pnl'])} → {_pnl(r['last_pnl'])}"
        status = "—"
        fp, lp = r["first_pnl"], r["last_pnl"]
        if isinstance(fp, (int, float)) and isinstance(lp, (int, float)):
            if lp > fp + 1: status = "📈 заработал"
            elif lp < fp - 1: status = "📉 потерял"
            else: status = "≈ без изменений"
        reasons = html.escape(r["reasons"] or "—")
        trs.append(
            f"<tr><td><a href='{link}' target='_blank'>{pseudo}</a></td>"
            f"<td>{flagged_date}</td><td>{r['first_score']:.0f} → {r['last_score']:.0f}</td>"
            f"<td>{wr_cell}</td><td>{pnl_cell}</td><td>{status}</td>"
            f"<td>{reasons}</td></tr>")
    body = "".join(trs) or "<tr><td colspan=7>Пока никого не помечали.</td></tr>"
    doc = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Помеченные аккаунты</title>
<style>
  body {{ font-family:system-ui,sans-serif; margin:0; background:#0e0f13; color:#e8e8ea; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:24px; }}
  h1 {{ font-size:22px; }} .sub {{ color:#9aa0a6; font-size:13px; margin-bottom:18px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #23252b; vertical-align:top; }}
  th {{ color:#9aa0a6; }} a {{ color:#8ab4f8; text-decoration:none; }}
</style></head><body><div class="wrap">
  <h1>📊 Помеченные аккаунты — кто заработал, кто нет</h1>
  <div class="sub">Обновлено: {ts} · всего помечено: {len(rows)} · «значение тогда → сейчас»</div>
  <table>
    <tr><th>Аккаунт</th><th>Помечен</th><th>Балл</th><th>Винрейт</th>
        <th>PnL</th><th>Итог</th><th>Аномалии</th></tr>
    {body}
  </table>
</div></body></html>"""
    out_path.write_text(doc, encoding="utf-8")
    return out_path


def main():
    conn = db.connect()
    results, cluster_pairs = analyze.score_wallets(conn)
    report.render(results, cluster_pairs)
    ensure_flagged_table(conn)
    now = int(time.time())
    new_items = update_flagged(conn, results, now)
    render_flagged(conn)

    if new_items:
        lines = [f"🔎 Новые подозрительные аккаунты: {len(new_items)}\n"]
        for r in new_items:
            anomalies = "; ".join(r["reasons"]) or "—"
            lines.append(
                f"• {r.get('pseudonym') or r['wallet'][:10]} — балл {r['score']:.0f}, "
                f"винрейт {_wr(r.get('pos_winrate'))}\n  аномалии: {anomalies}\n"
                f"  https://polymarket.com/profile/{r['wallet']}")
        telegram("\n".join(lines))

    print(f"Проанализировано кошельков: {len(results)}. Новых помеченных: {len(new_items)}.")
    print("Топ-10 по баллу:")
    for r in results[:10]:
        print(f"  {r['score']:5.1f}  {(r.get('pseudonym') or r['wallet'][:10]):<18}  "
              f"винрейт {_wr(r.get('pos_winrate'))}  | " + "; ".join(r['reasons'][:2]))


if __name__ == "__main__":
    main()
