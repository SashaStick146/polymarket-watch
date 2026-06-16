"""Клиент к публичным API Polymarket (без ключей — только чтение)."""
import time, logging
import requests

DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
log = logging.getLogger("api")


class PolymarketAPI:
    def __init__(self, pause: float = 0.4, timeout: int = 30, retries: int = 4):
        self.pause = pause; self.timeout = timeout; self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "polymarket-watch/1.0"})

    def _get(self, url, params=None):
        for attempt in range(1, self.retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 400:
                    return []  # обычно «страниц больше нет» — тихо выходим
                if r.status_code == 429:
                    wait = self.pause * (2 ** attempt)
                    log.warning("429, пауза %.1f c", wait); time.sleep(wait); continue
                r.raise_for_status(); time.sleep(self.pause); return r.json()
            except requests.RequestException as e:
                wait = self.pause * (2 ** attempt)
                log.warning("Запрос не удался (%s/%s): %s — пауза %.1f c", attempt, self.retries, e, wait)
                time.sleep(wait)
        log.error("Запрос окончательно провалился: %s", url); return []

    def trades(self, limit=500, offset=0, market=None, user=None):
        params = {"limit": limit, "offset": offset, "takerOnly": "false"}
        if market: params["market"] = market
        if user: params["user"] = user
        return self._get(f"{DATA_API}/trades", params)

    def activity(self, user, limit=500, offset=0):
        return self._get(f"{DATA_API}/activity", {"user": user, "limit": limit, "offset": offset})

    def positions(self, user, limit=500, offset=0):
        return self._get(f"{DATA_API}/positions", {"user": user, "limit": limit, "offset": offset})

    def price_history(self, market_token, interval="max"):
        return self._get(f"{CLOB_API}/prices-history", {"market": market_token, "interval": interval})
