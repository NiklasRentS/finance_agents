# finance_agents

Modularer Multi-Agent für fundamentale Aktienanalyse.

Das System erstellt strukturierte Investment-Research-Reports. Es trennt konsequent
zwischen Fakten, abgeleiteten Werten, Schätzungen und Modellannahmen. Jede externe
Information trägt ihre Quelle mit sich. Fehlende Daten werden als
`DATA NOT AVAILABLE` ausgewiesen und niemals ergänzt oder geschätzt.

> Dieses System führt ausschließlich Research durch. Es platziert keine Orders,
> nutzt keine Broker-API und gibt keine Kaufempfehlung als Gewissheit aus.

## Leitprinzipien

1. **Provenance by default** – kein nackter Zahlenwert in der Domäne, alles ist ein `Fact`.
2. **Rechnen ist deterministisch** – DCF, Multiples und Scores laufen in Python, nie im LLM.
3. **Ports & Adapters** – Datenquellen sind austauschbar, keine Kopplung an einen Anbieter.
4. **Kostenstufe 0** – Standardbetrieb ausschließlich mit kostenlosen Quellen und lokalem LLM.

## Technologie

- Python 3.12, FastAPI, Pydantic v2
- PostgreSQL 16 (via Docker)
- pandas / numpy für Finanzanalyse
- Lokales LLM über Ollama
- pytest, ruff, mypy

## Setup

```powershell
# 1. Virtuelle Umgebung
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Abhängigkeiten
pip install -e ".[dev]"

# 3. Konfiguration
Copy-Item .env.example .env

# 4. Infrastruktur starten (Postgres + Ollama)
docker compose up -d

# 5. Tests
pytest
```

### SEC-Zugriff konfigurieren

Die SEC verlangt einen identifizierenden User-Agent. Trage in der `.env` eine
gültige Kontaktadresse ein:

```
SEC_USER_AGENT="finance_agents/0.1 (deine.email@example.com)"
```

## Projektstruktur

```
app/
  domain/          Fachmodelle inkl. Provenance (Fact, Period, SourceRef)
  ports/           Abstrakte Provider-Interfaces
  providers/       Konkrete Adapter (SEC EDGAR, Marktdaten, LLM, MCP)
  agents/          Research, Financial, Filings, Valuation, Risk, ...
  services/        Kennzahlen, DCF, Multiples, Scoring, Diff, Report
  orchestration/   Pipeline-Ausführung
  repositories/    Persistenz (SQLAlchemy)
  infra/           HTTP, Cache, Rate-Limiting, Logging
  api/             FastAPI-Routen
tests/
```

## Status

Projekt im Aufbau.

- [x] Fundament: Konfiguration, Domänenmodelle mit Provenance
- [x] Infrastruktur: HTTP-Client, Cache, Rate-Limiter, Budgetkontrolle
- [x] Ports: austauschbare Provider-Interfaces
- [x] SEC-EDGAR-Adapter: Fundamentaldaten aus XBRL
- [ ] Marktdaten-Adapter, Kennzahlen-Service, Bewertung, Report

Integrationstests gegen die echte SEC-API laufen separat:

```powershell
pytest -m integration
```

