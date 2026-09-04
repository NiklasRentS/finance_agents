"""Yahoo Finance market data adapter.

Free daily prices without an API key via the public chart endpoint. This is an
undocumented endpoint and therefore treated as a replaceable source: everything
outside this module talks to :class:`MarketDataProvider`, so swapping in a paid
feed later touches this file only.

Stooq was evaluated first and rejected: it answers programmatic requests with a
JavaScript cookie challenge instead of CSV.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Self

from app.config.settings import Settings, get_settings
from app.domain.facts import Confidence, Fact, FactKind, SourceRef, SourceTier
from app.infra.cache import TTL_QUOTE, DiskCache
from app.infra.cost import CostTracker
from app.infra.http import HttpClient, HttpError
from app.infra.logging import get_logger
from app.infra.rate_limit import RateLimiter
from app.ports.exceptions import (
    CompanyNotFoundError,
    DataNotAvailableError,
    ProviderUnavailableError,
)
from app.ports.market_data import MarketDataProvider, PricePoint, Quote

logger = get_logger(__name__)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
HUMAN_URL = "https://finance.yahoo.com/quote/{ticker}/history"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
TTL_HISTORY = timedelta(hours=12)
REQUESTS_PER_SECOND = 2.0
DEFAULT_RANGE = "1mo"


class YahooFinanceMarketDataProvider(MarketDataProvider):
    name = "yahoo_finance"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    @classmethod
    def build(
        cls,
        settings: Settings | None = None,
        *,
        cache: DiskCache | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> Self:
        cfg = settings or get_settings()
        client = HttpClient(
            provider_name=cls.name,
            headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "application/json"},
            timeout=cfg.http_timeout_seconds,
            max_retries=cfg.http_max_retries,
            rate_limiter=RateLimiter(REQUESTS_PER_SECOND),
            cache=cache
            if cache is not None
            else DiskCache(cfg.cache_path, enabled=cfg.cache_enabled),
            cost_tracker=cost_tracker,
        )
        return cls(client)

    def close(self) -> None:
        self._http.close()

    def get_quote(self, ticker: str) -> Quote:
        symbol = _normalise(ticker)
        result = self._chart(symbol, params={"range": "5d", "interval": "1d"}, ttl=TTL_QUOTE)
        meta = result.get("meta", {})
        price = _to_float(meta.get("regularMarketPrice"))
        if price is None:
            raise DataNotAvailableError(self.name, f"no quote for {symbol!r}")
        as_of = _epoch_to_date(meta.get("regularMarketTime"), meta.get("gmtoffset"))
        currency = meta.get("currency")
        source = self._source(symbol, as_of, exchange=meta.get("fullExchangeName"))
        return Quote(
            ticker=symbol,
            price=Fact[float](
                value=price,
                unit=currency if isinstance(currency, str) else None,
                kind=FactKind.REPORTED,
                confidence=Confidence.HIGH,
                sources=[source],
                note="Last regular-session price, delayed",
            ),
            currency=currency if isinstance(currency, str) else None,
            as_of=as_of,
            source=source,
        )

    def get_historical_prices(
        self, ticker: str, *, start: date, end: date | None = None
    ) -> list[PricePoint]:
        symbol = _normalise(ticker)
        stop = end or date.today()
        params: dict[str, str | int] = {
            "period1": _to_epoch(start),
            "period2": _to_epoch(stop + timedelta(days=1)),
            "interval": "1d",
        }
        result = self._chart(symbol, params=params, ttl=TTL_HISTORY)
        return _parse_points(result)

    def _chart(
        self, symbol: str, *, params: dict[str, str | int], ttl: timedelta
    ) -> dict[str, Any]:
        try:
            payload = self._http.get_json(
                f"{CHART_URL}{symbol}", params=params, ttl=ttl, operation="chart"
            )
        except HttpError as exc:
            if exc.status_code == 404:
                raise CompanyNotFoundError(self.name, symbol) from exc
            raise ProviderUnavailableError(self.name, str(exc)) from exc
        return _first_result(payload, self.name, symbol)

    def _source(self, symbol: str, as_of: date | None, *, exchange: object) -> SourceRef:
        venue = f" ({exchange})" if isinstance(exchange, str) and exchange else ""
        return SourceRef(
            provider="Yahoo Finance",
            tier=SourceTier.FINANCIAL_DATA_PROVIDER,
            title=f"Daily price history for {symbol}{venue}",
            url=HUMAN_URL.format(ticker=symbol),
            document_id=symbol,
            published_at=as_of,
        )


def _normalise(ticker: str) -> str:
    cleaned = ticker.strip().upper()
    if not cleaned:
        raise ValueError("ticker must not be empty")
    return cleaned


def _first_result(payload: object, provider: str, symbol: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DataNotAvailableError(provider, f"unexpected response for {symbol!r}")
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise DataNotAvailableError(provider, f"unexpected response for {symbol!r}")
    error = chart.get("error")
    if error:
        description = error.get("description") if isinstance(error, dict) else str(error)
        raise CompanyNotFoundError(provider, f"{symbol}: {description}")
    results = chart.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise DataNotAvailableError(provider, f"no price data for {symbol!r}")
    return results[0]


def _parse_points(result: dict[str, Any]) -> list[PricePoint]:
    timestamps = result.get("timestamp")
    indicators = result.get("indicators", {})
    quotes = indicators.get("quote") if isinstance(indicators, dict) else None
    if not isinstance(timestamps, list) or not isinstance(quotes, list) or not quotes:
        return []
    quote = quotes[0] if isinstance(quotes[0], dict) else {}
    closes = _as_list(quote.get("close"))
    volumes = _as_list(quote.get("volume"))
    offset = result.get("meta", {}).get("gmtoffset")

    points: list[PricePoint] = []
    for index, raw_timestamp in enumerate(timestamps):
        close = _to_float(closes[index]) if index < len(closes) else None
        day = _epoch_to_date(raw_timestamp, offset)
        if close is None or day is None:
            continue  # Yahoo pads holidays and halted sessions with nulls.
        volume = _to_float(volumes[index]) if index < len(volumes) else None
        points.append(PricePoint(date=day, close=close, volume=volume))
    points.sort(key=lambda point: point.date)
    return points


def _as_list(raw: object) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _to_float(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _to_epoch(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), tzinfo=UTC).timestamp())


def _epoch_to_date(raw: object, gmtoffset: object) -> date | None:
    """Convert an epoch seconds value to the trading date at the exchange."""
    seconds = _to_float(raw)
    if seconds is None:
        return None
    offset = _to_float(gmtoffset) or 0.0
    return datetime.fromtimestamp(seconds + offset, tz=UTC).date()
