"""
Аналитика и скоринг подозрительности (+ качество прибыли).
Балл 0..100. Высокий балл — повод присмотреться, НЕ доказательство.

КАЧЕСТВО ПРИБЫЛИ:
  consistency — насколько прибыль размазана по многим сделкам (1 = стабильно).
  one_hit — флаг «прибыль почти вся с 1 сделки»: такой кошелёк ПОНИЖАЕТСЯ.
  pnl_per_day, span_days — скорость и срок набора прибыли.
"""
import time
from datetime import datetime
from collections import defaultdict

WEIGHTS = {"winrate": 20, "big_bet": 16, "cluster": 14, "roi": 14,
           "consistency": 12, "late_high_conf": 8, "short_lifespan": 8,
           "flip_in_out": 6, "dormant_after_win": 4}

MIN_RESOLVED_FOR_WINRATE = 8
MIN_TRADES = 3
CLUSTER_WINDOW_SEC = 300
CLUSTER_MIN_SHARED = 4
FLIP_WINDOW_SEC = 1800
MIN_HISTORY_DAYS = 5
BIG_SINGLE_BET_USD = 15000
WHALE_VOLUME_USD = 80000
ONE_HIT_SHARE = 0.70
ONE_HIT_PENALTY = 0.55


def _clip01(x): return max(0.0, min(1.0, x))


def _days_between(d1, d2):
    try:
        a = datetime.strptime(d1[:10], "%Y-%m-%d")
        b = datetime.strptime(d2[:10], "%Y-%m-%d")
        return abs((b - a).days)
    except Exception:
        return 0


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
                  SUM(realized_pnl) AS pnl, SUM(initial_value) AS invested,
                  MAX(realized_pnl) AS best,
                  SUM(CASE WHEN realized_pnl>0 THEN realized_pnl ELSE 0 END) AS pos_sum,
                  MIN(end_date) AS first_end, MAX(end_date) AS last_end
           FROM positions WHERE redeemable=1 GROUP BY wallet""").fetchall()
    out = {}
    for r in rows:
        n = r["n_resolved"] or 0
        invested = r["invested"] or 0
        pnl = r["pnl"] or 0
        best = r["best"] or 0
        pos_sum = r["pos_sum"] or 0
        top1_share = (best / pos_sum) if pos_sum > 0 else None
        consistency = (1 - top1_share) if top1_share is not None else None
        span = _days_between(r["first_end"] or "", r["last_end"] or "")
        pnl_per_day = (pnl / span) if span > 0 else None
        out[r["wallet"]] = {
            "n_resolved": n,
            "winrate": (r["n_win"] / n) if n else None,
            "pnl": round(pnl, 2),
            "roi": (pnl / invested) if invested > 0 else None,
            "top1_share": top1_share,
            "consistency": consistency,
            "span_days": span,
            "pnl_per_day": round(pnl_per_day, 2) if pnl_per_day is not None else None,
        }
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
        nres = p.get("n_resolved", 0)
        sig = {}
        wr = p.get("winrate")
        sig["winrate"] = _clip01((wr - 0.55) / 0.40) if (wr is not None and nres >= MIN_RESOLVED_FOR_WINRATE) else 0.0
        roi = p.get("roi")
        sig["roi"] = _clip01(roi / 1.0) if (roi is not None and nres >= MIN_RESOLVED_FOR_WINRATE) else 0.0
        sig["big_bet"] = max(_clip01(b["max_trade"] / BIG_SINGLE_BET_USD), _clip01(b["volume"] / WHALE_VOLUME_USD))
        cons = p.get("consistency")
        sig["consistency"] = _clip01(cons) if (cons is not None and nres >= MIN_RESOLVED_FOR_WINRATE) else 0.0
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

        top1 = p.get("top1_share")
        one_hit = (top1 is not None and top1 > ONE_HIT_SHARE and nres >= 2)
        if one_hit:
            score *= ONE_HIT_PENALTY

        reasons = []
        if sig["winrate"] > 0.5: reasons.append(f"винрейт {wr:.0%} на {nres} рынках")
        if sig["roi"] > 0.4 and roi is not None: reasons.append(f"ROI {roi:.0%}")
        if sig["consistency"] > 0.5: reasons.append(f"стабильная прибыль (лучшая сделка {top1:.0%})")
        if sig["big_bet"] > 0.4: reasons.append(f"крупные ставки: макс ${b['max_trade']:,.0f}, оборот ${b['volume']:,.0f}")
        if sig["late_high_conf"] > 0.4: reasons.append(f"{b['share_high_conf']:.0%} входов по цене >0.9")
        if sig["short_lifespan"] > 0.4: reasons.append(f"жизнь {life:.0f} дн при обороте ${b['volume']:.0f}")
        if sig["dormant_after_win"] > 0.3: reasons.append(f"молчит {since:.0f} дн после прибыли ${p.get('pnl'):.0f}")
        if sig["flip_in_out"] > 0.3: reasons.append(f"{flips.get(w)} быстрых заходов-выходов")
        if sig["cluster"] > 0.3: reasons.append("синхронные входы с другими кошельками")
        if one_hit: reasons.append(f"⚠ прибыль почти вся с 1 сделки ({top1:.0%}) — понижено")

        res.append({**b, **{f"pos_{k}": v for k, v in p.items()},
            "lifespan_days": round(life, 1), "days_since_last": round(since, 1),
            "one_hit": one_hit, "signals": sig, "score": round(score, 1), "reasons": reasons})
    res.sort(key=lambda x: -x["score"])
    return res, cluster_pairs
