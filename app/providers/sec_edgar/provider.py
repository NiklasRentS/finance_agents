"""SEC EDGAR adapter.

Primary, free and authoritative source for US filers. Only values actually
present in a filing are emitted; nothing is interpolated or estimated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Self

import httpx

from app.config.settings import Settings, get_settings
from app.domain.company import Company, Listing
from app.domain.facts import (
    Confidence,
    Fact,
    FactKind,
    Period,
    PeriodType,
    SourceRef,
    SourceTier,
)
from app.domain.financials import FinancialHistory, FinancialSnapshot, Metric, NumericFact
from app.infra.cache import TTL_FUNDAMENTALS, TTL_IMMUTABLE, DiskCache
from app.infra.cost import CostTracker
from app.infra.http import HttpClient, HttpError
from app.infra.logging import get_logger
from app.infra.rate_limit import RateLimiter
from app.ports.exceptions import CompanyNotFoundError, ProviderUnavailableError
from app.ports.fundamentals import FundamentalsProvider
from app.providers.sec_edgar.tags import METRIC_TAGS, TagSpec

logger = get_logger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{accn}-index.htm"

ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "20-F", "20-F/A", "40-F"})
ANNUAL_MIN_DAYS = 300
ANNUAL_MAX_DAYS = 430
FISCAL_YEAR_PIVOT_MONTH = 6
"""Period ends before June are attributed to the previous fiscal year."""


def fiscal_year_for(period_end: date) -> int:
    """Normalise a period end date to a fiscal year label.

    Issuers label fiscal years inconsistently, so we apply one deterministic
    rule and always carry the exact ``end`` date alongside it.
    """
    return period_end.year if period_end.month >= FISCAL_YEAR_PIVOT_MONTH else period_end.year - 1


@dataclass(frozen=True)
class _Observation:
    value: float
    period_end: date
    tag: str
    taxonomy: str
    unit: str
    accession: str | None
    form: str | None
    filed: date | None


class SecEdgarFundamentalsProvider(FundamentalsProvider):
    name = "sec_edgar"

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
            headers={
                "User-Agent": cfg.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json",
            },
            timeout=cfg.http_timeout_seconds,
            max_retries=cfg.http_max_retries,
            rate_limiter=RateLimiter(cfg.sec_requests_per_second),
            cache=cache
            if cache is not None
            else DiskCache(cfg.cache_path, enabled=cfg.cache_enabled),
            cost_tracker=cost_tracker,
        )
        return cls(client)

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ #
    # Company resolution
    # ------------------------------------------------------------------ #

    def resolve_company(self, identifier: str) -> Company:
        cik = self._resolve_cik(identifier)
        submissions = self._get_json(
            SUBMISSIONS_URL.format(cik=cik),
            ttl=TTL_FUNDAMENTALS,
            operation="submissions",
            not_found_hint=f"CIK {cik}",
        )
        return self._company_from_submissions(cik, submissions)

    def _resolve_cik(self, identifier: str) -> str:
        cleaned = identifier.strip()
        if cleaned.isdigit():
            return cleaned.zfill(10)

        mapping = self._get_json(TICKERS_URL, ttl=TTL_FUNDAMENTALS, operation="company_tickers")
        wanted = cleaned.upper()
        for row in mapping.values() if isinstance(mapping, dict) else []:
            if str(row.get("ticker", "")).upper() == wanted:
                return str(row.get("cik_str", "")).zfill(10)
        raise CompanyNotFoundError(self.name, f"No SEC filer found for {identifier!r}")

    def _company_from_submissions(self, cik: str, payload: dict[str, Any]) -> Company:
        tickers = payload.get("tickers") or []
        exchanges = payload.get("exchanges") or []
        listings = [
            Listing(
                ticker=str(ticker),
                exchange=str(exchanges[index]) if index < len(exchanges) else None,
                is_primary=index == 0,
            )
            for index, ticker in enumerate(tickers)
        ]
        fiscal_end = str(payload.get("fiscalYearEnd") or "")
        source = SourceRef(
            provider="SEC EDGAR",
            tier=SourceTier.REGULATORY_FILING,
            title=f"EDGAR submissions for CIK {cik}",
            url=SUBMISSIONS_URL.format(cik=cik),
        )
        return Company(
            name=str(payload.get("name") or f"CIK {cik}"),
            cik=cik,
            listings=listings,
            industry=payload.get("sicDescription"),
            country=(payload.get("addresses") or {}).get("business", {}).get("stateOrCountry"),
            fiscal_year_end_month=int(fiscal_end[:2]) if len(fiscal_end) == 4 else None,
            sources=[source],
        )

    # ------------------------------------------------------------------ #
    # Financial history
    # ------------------------------------------------------------------ #

    def get_financial_history(
        self,
        company: Company,
        *,
        period_type: PeriodType = PeriodType.FISCAL_YEAR,
        max_periods: int = 10,
    ) -> FinancialHistory:
        if period_type is not PeriodType.FISCAL_YEAR:
            raise ValueError("SEC EDGAR adapter currently supports fiscal-year periods only")
        if not company.cik:
            raise CompanyNotFoundError(self.name, f"{company.name} has no CIK")

        payload = self._get_json(
            COMPANYFACTS_URL.format(cik=company.cik),
            ttl=TTL_IMMUTABLE,
            operation="companyfacts",
            not_found_hint=f"CIK {company.cik}",
        )
        facts = payload.get("facts") or {}

        observations: dict[Metric, dict[int, _Observation]] = {}
        for metric, spec in METRIC_TAGS.items():
            found = self._observations_for(facts, spec)
            if found:
                observations[metric] = found

        year_ends: dict[int, date] = {}
        for per_year in observations.values():
            for year, obs in per_year.items():
                if year not in year_ends or obs.period_end > year_ends[year]:
                    year_ends[year] = obs.period_end

        selected_years = sorted(year_ends)[-max_periods:]
        snapshots = [
            self._snapshot_for(company, year, year_ends[year], observations)
            for year in selected_years
        ]
        currency = self._detect_currency(observations)
        return FinancialHistory(currency=currency, snapshots=snapshots)

    def _observations_for(self, facts: dict[str, Any], spec: TagSpec) -> dict[int, _Observation]:
        """Merge observations across candidate tags, highest priority first.

        Filers switch tags over time, so a single tag rarely covers the whole
        history. Each fact records the tag it came from, keeping the mix auditable.
        """
        taxonomy_facts = facts.get(spec.taxonomy) or {}
        merged: dict[int, _Observation] = {}
        for tag in spec.tags:
            entry = taxonomy_facts.get(tag)
            if not entry:
                continue
            units = entry.get("units") or {}
            unit_name = self._pick_unit(units, spec.unit)
            if unit_name is None:
                continue
            for year, observation in self._select_annual(
                units[unit_name], spec, tag, unit_name
            ).items():
                merged.setdefault(year, observation)
        return merged

    @staticmethod
    def _pick_unit(units: dict[str, Any], preferred: str) -> str | None:
        if preferred in units:
            return preferred
        return next(iter(units)) if len(units) == 1 else None

    def _select_annual(
        self, rows: list[dict[str, Any]], spec: TagSpec, tag: str, unit_name: str
    ) -> dict[int, _Observation]:
        newest_per_end: dict[date, dict[str, Any]] = {}
        for row in rows:
            if row.get("form") not in ANNUAL_FORMS:
                continue
            end_raw, value = row.get("end"), row.get("val")
            if end_raw is None or value is None:
                continue
            end = date.fromisoformat(str(end_raw))
            start_raw = row.get("start")
            if spec.instant:
                if start_raw is not None:
                    continue
            else:
                if start_raw is None:
                    continue
                span = (end - date.fromisoformat(str(start_raw))).days
                if not ANNUAL_MIN_DAYS <= span <= ANNUAL_MAX_DAYS:
                    continue
            previous = newest_per_end.get(end)
            # A restated figure filed later supersedes the original.
            if previous is None or str(row.get("filed", "")) > str(previous.get("filed", "")):
                newest_per_end[end] = row

        by_year: dict[int, _Observation] = {}
        for end, row in newest_per_end.items():
            year = fiscal_year_for(end)
            existing = by_year.get(year)
            if existing is not None and existing.period_end >= end:
                continue
            filed_raw = row.get("filed")
            by_year[year] = _Observation(
                value=float(row["val"]),
                period_end=end,
                tag=tag,
                taxonomy=spec.taxonomy,
                unit=unit_name,
                accession=row.get("accn"),
                form=row.get("form"),
                filed=date.fromisoformat(str(filed_raw)) if filed_raw else None,
            )
        return by_year

    def _snapshot_for(
        self,
        company: Company,
        year: int,
        period_end: date,
        observations: dict[Metric, dict[int, _Observation]],
    ) -> FinancialSnapshot:
        period = Period.fiscal_year_of(year, end=period_end)
        values: dict[Metric, NumericFact] = {}
        for metric, per_year in observations.items():
            obs = per_year.get(year)
            if obs is None:
                continue
            values[metric] = Fact[float](
                value=obs.value,
                unit=obs.unit,
                period=period,
                kind=FactKind.REPORTED,
                confidence=Confidence.HIGH,
                sources=[self._source_for(company, obs)],
            )
        return FinancialSnapshot(period=period, values=values)

    def _source_for(self, company: Company, obs: _Observation) -> SourceRef:
        url = None
        if obs.accession and company.cik:
            url = FILING_INDEX_URL.format(
                cik=int(company.cik),
                accession=obs.accession.replace("-", ""),
                accn=obs.accession,
            )
        return SourceRef(
            provider="SEC EDGAR",
            tier=SourceTier.REGULATORY_FILING,
            title=f"{company.name} {obs.form or 'filing'}",
            url=url,
            document_id=obs.accession,
            locator=f"{obs.taxonomy}:{obs.tag}",
            published_at=obs.filed,
        )

    @staticmethod
    def _detect_currency(observations: dict[Metric, dict[int, _Observation]]) -> str | None:
        for per_year in observations.values():
            for obs in per_year.values():
                if obs.unit.isalpha() and len(obs.unit) == 3:
                    return obs.unit
        return None

    # ------------------------------------------------------------------ #

    def _get_json(
        self,
        url: str,
        *,
        ttl: Any,
        operation: str,
        not_found_hint: str | None = None,
    ) -> Any:
        try:
            return self._http.get_json(url, ttl=ttl, operation=operation)
        except HttpError as exc:
            if exc.status_code == httpx.codes.NOT_FOUND and not_found_hint:
                raise CompanyNotFoundError(
                    self.name, f"EDGAR has no data for {not_found_hint}"
                ) from exc
            raise ProviderUnavailableError(self.name, str(exc)) from exc
