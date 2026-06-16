"""HTML-отчёты: основной (подозрительные кошельки) и по списку наблюдения."""
import time, html
from pathlib import Path

REPORT_PATH = Path(__file__).resolve().parent.parent / "report.html"
WATCH_REPORT_PATH = Path(__file__).resolve().parent.parent / "watch_report.html"


def _bar(value: float) -> str:
    pct = int(max(0, min(100, value)))
    color = "#d64545" if pct >= 60 else "#e0883a" if pct >= 35 else "#3a7bd5"
    return (f'<div class="bar"><div class="fill" style="width:{pct}%;'
            f'background:{color}"></div><span>{pct}</span></div>')


def render(results: list, cluster_pairs: list, top: int = 80, out_path: Path = REPORT_PATH) -> Path:
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    rows_html = []
    for r in results[:top]:
        pseudo = html.escape(r.get("pseudonym") or "—"); wallet = r["wallet"]
        short = wallet[:6] + "…" + wallet[-4:]
        link = f"https://polymarket.com/profile/{wallet}"
        reasons = "; ".join(html.escape(x) for x in r["reasons"]) or "—"
        rows_html.append(
            f"<tr><td>{_bar(r['score'])}</td>"
            f"<td><a href='{link}' target='_blank'>{pseudo}</a><br><code>{short}</code></td>"
            f"<td>{r['n_trades']}</td><td>${r['volume']:,.0f}</td><td>{r['n_markets']}</td>"
            f"<td>{r['lifespan_days']:.0f} дн</td><td class='reasons'>{reasons}</td></tr>")

    def fmt_pct(v): return f"{v:.0%}" if isinstance(v, (int, float)) else "—"
    whales = sorted(results, key=lambda r: -r.get("volume", 0))[:25]
    whales_html = []
    for r in whales:
        wallet = r["wallet"]; link = f"https://polymarket.com/profile/{wallet}"
        pseudo = html.escape(r.get("pseudonym") or "—")
        wr = r.get("pos_winrate"); roi = r.get("pos_roi"); pnl = r.get("pos_pnl")
        nres = r.get("pos_n_resolved") or 0
        pnl_str = f"${pnl:,.0f}" if isinstance(pnl, (int, float)) else "—"
        whales_html.append(
            f"<tr><td><a href='{link}' target='_blank'>{pseudo}</a></td>"
            f"<td>${r.get('volume', 0):,.0f}</td><td>${r.get('max_trade', 0):,.0f}</td>"
            f"<td>{fmt_pct(wr)}</td><td>{fmt_pct(roi)}</td><td>{pnl_str}</td><td>{nres}</td></tr>")

    pairs_html = []
    for a, b, c in cluster_pairs[:40]:
        la = f"https://polymarket.com/profile/{a}"; lb = f"https://polymarket.com/profile/{b}"
        pairs_html.append(
            f"<tr><td><a href='{la}' target='_blank'><code>{a[:10]}…</code></a></td>"
            f"<td><a href='{lb}' target='_blank'><code>{b[:10]}…</code></a></td><td>{c}</td></tr>")

    doc = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polymarket Watch</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin:0; background:#0e0f13; color:#e8e8ea; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:24px; }}
  h1 {{ font-size:22px; }} h2 {{ font-size:16px; margin-top:34px; }}
  .sub {{ color:#9aa0a6; font-size:13px; margin-bottom:20px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #23252b; vertical-align:top; }}
  th {{ color:#9aa0a6; font-weight:600; }}
  code {{ color:#8ab4f8; font-size:12px; }} a {{ color:#8ab4f8; text-decoration:none; }}
  .reasons {{ color:#cfd2d6; max-width:340px; }}
  .bar {{ position:relative; width:120px; height:18px; background:#1c1e24; border-radius:4px; }}
  .fill {{ height:100%; border-radius:4px; }}
  .bar span {{ position:absolute; right:6px; top:0; font-size:11px; line-height:18px; color:#fff; }}
  .note {{ background:#1c1e24; border-left:3px solid #e0883a; padding:10px 14px; border-radius:4px;
           font-size:12px; color:#cfd2d6; margin:18px 0; }}
</style></head><body><div class="wrap">
  <h1>🔎 Polymarket Watch — подозрительные аккаунты</h1>
  <div class="sub">Сформирован: {ts} · в рейтинге: {min(top, len(results))} из {len(results)}</div>
  <div class="note">⚠️ Высокий балл — повод присмотреться, а НЕ доказательство нарушения.
  Аномалия может объясняться удачей или мастерством трейдера. Это список приоритетов для ручной проверки.</div>
  <table>
    <tr><th>Балл</th><th>Аккаунт</th><th>Сделок</th><th>Оборот</th><th>Рынков</th><th>Жизнь</th><th>Почему в списке</th></tr>
    {''.join(rows_html)}
  </table>
  <h2>🐋 Киты — крупнейшие по обороту (умные деньги?)</h2>
  <div class="sub">Смотри на сочетание: большой оборот + высокий винрейт/ROI.</div>
  <table>
    <tr><th>Аккаунт</th><th>Оборот</th><th>Макс. ставка</th><th>Винрейт</th><th>ROI</th><th>PnL</th><th>Закрытых</th></tr>
    {''.join(whales_html) or '<tr><td colspan=7>Нет данных.</td></tr>'}
  </table>
  <h2>🔗 Возможные связки аккаунтов (синхронные входы)</h2>
  <table>
    <tr><th>Кошелёк A</th><th>Кошелёк B</th><th>Совместных входов</th></tr>
    {''.join(pairs_html) or '<tr><td colspan=3>Связок не найдено на текущем объёме данных.</td></tr>'}
  </table>
</div></body></html>"""
    out_path.write_text(doc, encoding="utf-8")
    return out_path


def render_watch(watch_results: list, out_path: Path = WATCH_REPORT_PATH) -> Path:
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    rows = []; total = 0
    for r in watch_results:
        addr = r["address"]; label = html.escape(r.get("label") or "")
        link = f"https://polymarket.com/profile/{addr}"; short = addr[:6] + "…" + addr[-4:]
        for a in r.get("new", []):
            total += 1
            when = time.strftime("%m-%d %H:%M", time.gmtime(int(a.get("timestamp") or 0)))
            side = html.escape(a.get("side") or ""); outcome = html.escape(a.get("outcome") or "")
            title = html.escape(a.get("title") or "")
            usd = float(a.get("usdcSize") or 0); price = float(a.get("price") or 0)
            color = "#3a7bd5" if side == "BUY" else "#d64545"
            rows.append(
                f"<tr><td>{when}</td><td><a href='{link}' target='_blank'>{label or short}</a>"
                f"<br><code>{short}</code></td><td style='color:{color}'>{side} {outcome}</td>"
                f"<td>${usd:,.0f}</td><td>{price:.2f}</td><td>{title}</td></tr>")
    body = "".join(rows) or "<tr><td colspan=6>Новых ставок нет (или это первый запуск — задаётся точка отсчёта).</td></tr>"
    doc = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Watchlist — новые ставки</title>
<style>
  body {{ font-family:system-ui,sans-serif; margin:0; background:#0e0f13; color:#e8e8ea; }}
  .wrap {{ max-width:1000px; margin:0 auto; padding:24px; }}
  h1 {{ font-size:22px; }} .sub {{ color:#9aa0a6; font-size:13px; margin-bottom:18px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #23252b; }}
  th {{ color:#9aa0a6; }} a {{ color:#8ab4f8; text-decoration:none; }} code {{ color:#8ab4f8; font-size:11px; }}
</style></head><body><div class="wrap">
  <h1>👀 Список наблюдения — новые ставки</h1>
  <div class="sub">Обновлено: {ts} · новых ставок: {total}</div>
  <table>
    <tr><th>Время (UTC)</th><th>Кошелёк</th><th>Сделка</th><th>Сумма</th><th>Цена</th><th>Рынок</th></tr>
    {body}
  </table>
</div></body></html>"""
    out_path.write_text(doc, encoding="utf-8")
    return out_path
