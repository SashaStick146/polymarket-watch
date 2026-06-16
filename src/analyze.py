"""
Аналитика и скоринг подозрительности.

По собранным сделкам и позициям считаем для каждого кошелька набор сигналов,
затем общий балл 0..100. Чем выше — тем больше поводов присмотреться.

ВАЖНО: высокий балл — НЕ доказательство нарушения, а приоритет для ручной
проверки. Аномалия может объясняться удачей или мастерством трейдера.

Сигналы: винрейт, ROI, «кит»/умные деньги (крупные ставки), систематический
вход по «почти решённой» цене (>0.9), короткая жизнь при большом обороте,
«замолчал после прибыли», быстрые BUY→SELL, синхронные входы (связки).
"""
import time
from collections import defaultdict

WEIGHTS = {"winrate": 22, "roi": 16, "big_bet": 16, "cluster": 14,
           "late_high_conf": 10, "short_lifespan": 10, "flip_in_out": 8,
           "dormant_after_win": 6}

MIN_RESOLVED_FOR_WINRATE = 8
MIN_TRADES = 3
CLUSTER_WINDOW_SEC = 300
CLUSTER_MIN_SHARED = 4
FLIP_WINDOW_SEC = 1800
MIN_HISTORY_DAYS = 5          # сигналы про «время жизни» — только при накопленной истории
BIG_SINGLE_BET_USD = 15000    # одиночная ставка такого размера -> полный сигнал «кит»
WHALE_VOLUME_USD = 80000      # суммарный оборот -> полный сигнал «кит»


def _clip01(x): return max(0.0, min(1.0, x))


def wallet_trade_stats(conn) -> dict:
    rows = conn.execute(
        """SELECT wallet, COUNT(*) AS n_trades, SUM(usd) AS volume,
                  COUNT(DISTINCT condition_id) AS n_markets, MIN(ts) AS first_ts,
                  MAX(ts) AS last_ts, MAX(usd) AS max_trade,
                  AVG(CASE WHEN side='BUY' AND price>0.9 THEN 1.0 ELSE 0.0 END) AS share_high_conf,
                  MAX(pseudonym) AS pseudonym
           FROM trades GROUP BY wallet""").fetchall()
    s = {}
    for r in rows:
        s[r["wallet"]] = {"wallet": r["wallet"], "pseudonym": r["pseudonym"] or "",
            "n_trades": r["n_trades"], "volume": round(r["volume"] or 0, 2),
            "max_trade": round(r["max_trade"] or 0, 2), "n_markets": r["n_markets"],
            "first_ts": r["first_ts"], "last_ts": r["last_ts"],
            "share_high_conf": r["share_high_conf"] or 0.0}
    return s


def wallet_position_stats(conn) -> dict:
    rows = conn.execute(
        """SELECT wallet, COUNT(*) AS n_resolved,
                  SUM(CASE WHEN realized_pnl>0 THEN 1 ELSE 0 END) AS n_win,
                  SUM(realized_pnl) AS pnl, SUM(initial_value) AS invested
           FROM positions WHERE redeemable=1 GROUP BY wallet""").fetchall()
    out = {}
    for r in rows:
        n = r["n_resolved"] or 0; invested = r["invested"] or 0
        out[r["wallet"]] = {"n_resolved": n, "winrate": (r["n_win"]/n) if n else None,
            "pnl": round(r["pnl"] or 0, 2), "roi": (r["pnl"]/invested) if invested > 0 else None}
    return out


def detect_flips(conn) -> dict:
    rows = conn.execute("SELECT wallet, asset, side, ts FROM trades ORDER BY wallet, asset, ts").fetchall()
    by = defaultdict(list)
    for r in rows: by[(r["wallet"], r["asset"])].append((r["ts"], r["side"]))
    flips = defaultdict(int)
    for (w, _a), ev in by.items():
        lb = None
        for ts, side in ev:
            if side == "BUY": lb = ts
            elif side == "SELL" and lb is not None:
                if 0 <= ts - lb <= FLIP_WINDOW_SEC: flips[w] += 1; lb = None
    return dict(flips)


def detect_clusters(conn):
    rows = conn.execute("SELECT wallet, asset, ts FROM trades WHERE side='BUY' ORDER BY asset, ts").fetchall()
    by = defaultdict(list)
    for r in rows: by[r["asset"]].append((r["ts"], r["wallet"]))
    pc = defaultdict(int)
    for _a, ev in by.items():
        ev.sort()
        for i in range(len(ev)):
            ti, wi = ev[i]
            for j in range(i + 1, len(ev)):
                tj, wj = ev[j]
                if tj - ti > CLUSTER_WINDOW_SEC: break
                if wi != wj: pc[tuple(sorted((wi, wj)))] += 1
    pairs = [(a, b, c) for (a, b), c in pc.items() if c >= CLUSTER_MIN_SHARED]
    pairs.sort(key=lambda x: -x[2])
    st = defaultdict(int)
    for a, b, c in pairs: st[a] = max(st[a], c); st[b] = max(st[b], c)
    return {w: _clip01(c / 20.0) for w, c in st.items()}, pairs


def score_wallets(conn):
    now = int(time.time())
    base = wallet_trade_stats(conn); pos = wallet_position_stats(conn)
    flips = detect_flips(conn); cs, cluster_pairs = detect_clusters(conn)
    af = [b["first_ts"] for b in base.values() if b["first_ts"]]
    al = [b["last_ts"] for b in base.values() if b["last_ts"]]
    span = ((max(al) - min(af)) / 86400.0) if af else 0.0
    ready = span >= MIN_HISTORY_DAYS

    res = []
    for w, b in base.items():
        if b["n_trades"] < MIN_TRADES: continue
        p = pos.get(w, {})
        life = max((b["last_ts"] - b["first_ts"]) / 86400.0, 0.0)
        since = (now - b["last_ts"]) / 86400.0
        sig = {}
        wr = p.get("winrate")
        sig["winrate"] = _clip01((wr - 0.55) / 0.40) if (wr is not None and p.get("n_resolved", 0) >= MIN_RESOLVED_FOR_WINRATE) else 0.0
        roi = p.get("roi")
        sig["roi"] = _clip01(roi / 1.0) if (roi is not None and p.get("n_resolved", 0) >= MIN_RESOLVED_FOR_WINRATE) else 0.0
        sig["big_bet"] = max(_clip01(b["max_trade"] / BIG_SINGLE_BET_USD), _clip01(b["volume"] / WHALE_VOLUME_USD))
        sig["late_high_conf"] = _clip01(b["share_high_conf"])
        if ready:
            short = 1.0 if (life <= 30 and b["volume"] >= 1000) else _clip01((30 - life) / 30.0) * _clip01(b["volume"] / 5000.0)
            sig["short_lifespan"] = _clip01(short)
        else:
            sig["short_lifespan"] = 0.0
        d = 0.0
        if ready and since >= 21 and (p.get("pnl") or 0) > 0: d = _clip01(since / 90.0)
        sig["dormant_after_win"] = d
        sig["flip_in_out"] = _clip01(flips.get(w, 0) / 10.0)
        sig["cluster"] = cs.get(w, 0.0)
        score = sum(WEIGHTS[k] * v for k, v in sig.items())

        reasons = []
        if sig["winrate"] > 0.5: reasons.append(f"винрейт {wr:.0%} на {p.get('n_resolved')} рынках")
        if sig["roi"] > 0.4 and roi is not None: reasons.append(f"ROI {roi:.0%}")
        if sig["big_bet"] > 0.4: reasons.append(f"крупные ставки: макс ${b['max_trade']:,.0f}, оборот ${b['volume']:,.0f}")
        if sig["late_high_conf"] > 0.4: reasons.append(f"{b['share_high_conf']:.0%} входов по цене >0.9")
        if sig["short_lifespan"] > 0.4: reasons.append(f"жизнь {life:.0f} дн при обороте ${b['volume']:.0f}")
        if sig["dormant_after_win"] > 0.3: reasons.append(f"молчит {since:.0f} дн после прибыли ${p.get('pnl'):.0f}")
        if sig["flip_in_out"] > 0.3: reasons.append(f"{flips.get(w)} быстрых заходов-выходов")
        if sig["cluster"] > 0.3: reasons.append("синхронные входы с другими кошельками")

        res.append({**b, **{f"pos_{k}": v for k, v in p.items()},
            "lifespan_days": round(life, 1), "days_since_last": round(since, 1),
            "signals": sig, "score": round(score, 1), "reasons": reasons})
    res.sort(key=lambda x: -x["score"])
    return res, cluster_pairs
