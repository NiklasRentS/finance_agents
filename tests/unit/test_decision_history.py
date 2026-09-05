from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.domain.decision import DecisionCategory
from app.domain.decision_history import WatchlistAttentionResponse
from app.repositories.analysis_store import SqlAnalysisStore
from app.repositories.models import AnalysisRunRow
from app.services.analysis import analyse_company
from app.services.decision_history import DecisionHistoryService
from tests.fakes import CompleteFakeFundamentals, ConfigurableFakeMarketData


def _analysis():
    return analyse_company(
        "EXMP",
        fundamentals=CompleteFakeFundamentals(),
        market_data=ConfigurableFakeMarketData(),
    )


def _store() -> tuple[Engine, SqlAnalysisStore]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    store = SqlAnalysisStore(engine)
    store.create_schema()
    return engine, store


def test_history_without_previous_run_is_explicit() -> None:
    engine, store = _store()
    run_id = store.save_run(_analysis())

    history = DecisionHistoryService(store).compare_latest("EXMP")

    assert history is not None
    assert history.current_run_id == str(run_id)
    assert history.previous_run_id is None
    assert history.decision_changed is False
    assert "Keine vorherige" in history.important_change
    engine.dispose()


def test_history_detects_decision_valuation_and_risk_changes() -> None:
    engine, store = _store()
    first_id = store.save_run(_analysis())
    second_id = store.save_run(_analysis())
    with Session(engine) as session:
        first = session.get(AnalysisRunRow, first_id)
        second = session.get(AnalysisRunRow, second_id)
        assert first is not None and second is not None
        first_brief = dict(first.decision_brief or {})
        second_brief = dict(second.decision_brief or {})
        first_brief["decision"] = DecisionCategory.WATCH.value
        second_brief["decision"] = DecisionCategory.CAUTION.value
        second_brief["key_risks"] = ["New risk"]
        second_brief["valuation_summary"] = {"interpretation": "changed"}
        first.decision_brief = first_brief
        second.decision_brief = second_brief
        session.commit()

    history = DecisionHistoryService(store).compare_latest("EXMP")

    assert history is not None
    assert history.previous_decision is DecisionCategory.WATCH
    assert history.current_decision is DecisionCategory.CAUTION
    assert history.decision_changed
    assert history.valuation_change == "changed"
    assert history.risk_change == "changed"
    assert history.key_changes
    engine.dispose()


def test_watchlist_attention_prioritizes_changed_caution_items() -> None:
    engine, store = _store()
    first_id = store.save_run(_analysis())
    second_id = store.save_run(_analysis())
    store.add_watchlist_item(ticker="EXMP", company_name="Example Corp.")
    with Session(engine) as session:
        first = session.get(AnalysisRunRow, first_id)
        second = session.get(AnalysisRunRow, second_id)
        assert first is not None and second is not None
        first_brief = dict(first.decision_brief or {})
        second_brief = dict(second.decision_brief or {})
        first_brief["decision"] = DecisionCategory.WATCH.value
        second_brief["decision"] = DecisionCategory.CAUTION.value
        first.decision_brief = first_brief
        second.decision_brief = second_brief
        session.commit()

    response = DecisionHistoryService(store).watchlist_attention(limit=3)

    assert isinstance(response, WatchlistAttentionResponse)
    assert response.items[0].ticker == "EXMP"
    assert response.items[0].priority >= 5
    engine.dispose()
