"""
Алерты в Telegram (необязательно).
Если заданы TELEGRAM_TOKEN и TELEGRAM_CHAT_ID — шлём сообщения, иначе тихо пропускаем.
"""
import os, logging
log = logging.getLogger("alerts")


def send_alert(results, threshold=60.0, max_items=10):
    token = os.getenv("TELEGRAM_TOKEN"); chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.info("Telegram не настроен — пропускаю алерт."); return
    import requests
    flagged = [r for r in results if r["score"] >= threshold][:max_items]
    if not flagged:
        log.info("Нет кошельков выше порога %.0f.", threshold); return
    lines = [f"🔎 Polymarket Watch: {len(flagged)} подозрительных аккаунтов\n"]
    for r in flagged:
        pseudo = r.get("pseudonym") or r["wallet"][:10]
        reasons = "; ".join(r["reasons"][:2]) or "—"
        lines.append(f"• {pseudo} — балл {r['score']:.0f}\n  {reasons}\n  https://polymarket.com/profile/{r['wallet']}")
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": "\n".join(lines), "disable_web_page_preview": "true"}, timeout=30)
        log.info("Алерт отправлен (%s шт.).", len(flagged))
    except requests.RequestException as e:
        log.warning("Не удалось отправить алерт: %s", e)


def send_watch_alert(watch_results, max_items=20):
    token = os.getenv("TELEGRAM_TOKEN"); chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.info("Telegram не настроен — пропускаю watch-алерт."); return
    import requests
    blocks = []; count = 0
    for r in watch_results:
        if not r.get("new"):
            continue
        who = r.get("label") or r["address"][:10]
        link = f"https://polymarket.com/profile/{r['address']}"
        lines = [f"• {who}\n  {link}"]
        for a in r["new"]:
            count += 1
            usd = float(a.get("usdcSize") or 0)
            lines.append(f"  {a.get('side','')} {a.get('outcome','')} "
                         f"${usd:,.0f} @ {float(a.get('price') or 0):.2f} — {a.get('title','')}")
        blocks.append("\n".join(lines))
    if not blocks:
        log.info("Новых ставок у отслеживаемых кошельков нет."); return
    text = "👀 Новые ставки отслеживаемых кошельков:\n\n" + "\n\n".join(blocks[:max_items])
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}, timeout=30)
        log.info("Watch-алерт отправлен (%s ставок).", count)
    except requests.RequestException as e:
        log.warning("Не удалось отправить watch-алерт: %s", e)
