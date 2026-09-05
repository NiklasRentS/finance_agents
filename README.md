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

### Analyse ausführen

```powershell
# Report auf der Konsole
finance-agents analyze AAPL

# Report als Datei, mit eigenen Bewertungsannahmen
finance-agents analyze MSFT --wacc 0.085 --terminal-growth 0.025 --output reports/MSFT.md

# Ohne Marktdaten (nur Fundamentaldaten der SEC)
finance-agents analyze AAPL --skip-market-data
```

Ohne Installation als Skript geht auch `python -m app.cli analyze AAPL`.
Jeder Wert im Report trägt eine Quellenangabe; geschätzte Werte sind mit
`[ASSUMPTION]`, unsichere mit `[LOW CONFIDENCE]` und fehlende mit
`DATA NOT AVAILABLE` gekennzeichnet. Der Report ist eine Datenaufbereitung und
ausdrücklich keine Kauf- oder Verkaufsempfehlung.

### Läufe speichern

Einmalig das Schema anlegen (Postgres muss laufen):

```powershell
docker compose up -d postgres
alembic upgrade head
```

Danach lassen sich Läufe speichern und später wieder abrufen:

```powershell
finance-agents analyze AAPL --save
finance-agents runs --ticker AAPL
finance-agents report <lauf-kennung>
```

Gespeichert werden der Report im Original, alle Kennzahlen je Periode samt
Quellen sowie die verwendeten Bewertungsannahmen. Damit sind später Historie,
Vergleiche zwischen Läufen und Benachrichtigungen bei Änderungen möglich.

### API für Historie, Vergleiche und Watchlist

Die gespeicherten Research-Daten sind zusätzlich über FastAPI erreichbar:

```powershell
alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.api:app --reload
```

Wichtige Endpunkte:

- `GET /api/v1/runs` - gespeicherte Läufe
- `GET /api/v1/runs/{id}/history` - Fakten inklusive Quellen je Periode
- `GET /api/v1/runs/{id}/diff?other_run_id={id}` - deterministischer Vergleich
- `GET /api/v1/alerts?ticker=AAPL&threshold=0.10` - große Änderungen zwischen den letzten zwei Läufen
- `GET` und `POST /api/v1/watchlist` - lokale Research-Watchlist

Alerts markieren ausschließlich messbare Änderungen. Sie sind keine Kauf- oder
Verkaufssignale und führen keine Orders aus.

### Read-only Broker-Import (Phase 1)

Trade Republic wird ausschließlich als Read-only-Datenquelle behandelt. Es gibt
keine Order-, Kauf-, Verkaufs-, Storno- oder Transfer-Funktion und das Projekt
speichert keine Trade-Republic-Zugangsdaten oder Session-Tokens.

Da Trade Republic aktuell keine öffentlich dokumentierte Kunden-API für diesen
Zweck bereitstellt, verwendet Phase 1 bewusst noch keinen privaten API-Aufruf
und kein Login-Scraping. Stattdessen gibt es einen lokalen, versionierten
Fixture-Adapter. Er akzeptiert ausschließlich das explizit gekennzeichnete
Format `finance-agents-trade-republic-export-v1`.

Die generischen Modelle befinden sich in `app/domain/broker.py`, der Read-only-
Port in `app/ports/broker.py` und der lokale Adapter in
`app/providers/trade_republic/export.py`. ISIN ist die zentrale
Instrumentenkennung; Geldwerte und Stückzahlen werden als Decimal verarbeitet.

Der anonymisierte Testimport kann ohne Brokerzugang ausgeführt werden:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_broker_import.py -q
```

Die Fixture liegt in `tests/fixtures/trade_republic_v1.json` und demonstriert:

- Positionen und Transaktionen in EUR und USD
- externe Transaktions-IDs
- Fingerprint-basierte IDs für Transaktionen ohne externe ID
- wiederholten Import ohne Duplikate
- ungültige Zeilen und fehlende Pflichtfelder

Ein anonymisierter echter Export kann später gegen dieses Format geprüft und
mit einem konkreten Mapping ergänzt werden. Persönliche Brokerdaten bleiben
lokal und werden nicht an das LLM gesendet.

Die read-only Portfolio-Abfragen sind über einen separaten API-Router verfügbar:

```text
GET /api/v1/portfolio
GET /api/v1/portfolio/positions
GET /api/v1/portfolio/cash
GET /api/v1/portfolio/transactions
GET /api/v1/portfolio/imports
```

Die Routen lesen ausschließlich lokal importierte Daten. Ein Datei-Upload für
den Import wird erst nach Prüfung eines anonymisierten echten Exports ergänzt.

### Persönliches Frontend (Phase 4)

Das Frontend liegt unabhängig vom Python-Backend in `frontend/` und verwendet
React, TypeScript, Vite, Recharts und Lucide. Es greift ausschließlich über
FastAPI auf Daten zu; PostgreSQL, Broker, SEC, Yahoo und Ollama werden nicht
direkt aus dem Browser angesprochen.

Backend starten:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --reload
```

In einem zweiten PowerShell-Fenster:

```powershell
cd frontend
npm install
npm run dev
```

Der Vite-Entwicklungsserver proxied `/api` lokal an `http://127.0.0.1:8000`.
Wenn das Backend nicht erreichbar ist, zeigt das Dashboard einen sichtbaren
Hinweis und anonymisierte Demo-Daten, statt eine leere oder kaputte Oberfläche
zu rendern.

Eine Analyse kann aus dem Frontend oder direkt über die API gestartet werden:

```text
POST /api/v1/analysis       {"ticker":"AAPL"}
GET  /api/v1/analysis/{id}
```

Der POST-Aufruf liefert `202 Accepted` und eine Job-ID. Die eigentliche
Analyse läuft im Backend und speichert nach erfolgreichem Abschluss einen
normalen Research-Run. Bei einem Fehler wird der Jobstatus auf `failed` gesetzt;
es werden keine Research-Berechnungen im Browser ausgeführt.

Das Frontend fragt den Jobstatus bis zum Abschluss oder Fehler ab und lädt den
Dashboard-Stand danach neu. Für gespeicherte Runs werden außerdem strukturierte
Catalyst-Observations persistiert und auf der Stock-Detailseite separat von
Risiken, Szenarien und dem menschenlesbaren Report angezeigt. Diese Hinweise
sind faktengebundene Research-Beobachtungen und keine Handlungsaufforderungen.

### Persistente Analysis Jobs

Analysis Jobs werden in PostgreSQL in `analysis_jobs` persistiert. Ein
Neustart der FastAPI-Anwendung verliert dadurch weder Status noch Fehlerdetails.
Jobs verwenden die Zustände `queued`, `running`, `completed`, `failed` und
`cancelled`. Ein abgeschlossener Job verweist über `analysis_run_id` direkt auf
den bestehenden Research-Run; es entsteht keine zweite Analysehistorie.

```text
POST /api/v1/analysis                 - Job erstellen und starten
GET  /api/v1/analysis                 - letzte Jobs auflisten
GET  /api/v1/analysis/{job_id}        - persistenten Status abrufen
POST /api/v1/analysis/{job_id}/cancel - queued/running Job abbrechen
```

Die Migration dafür ist `0006_analysis_jobs`. Fehler werden als begrenzte,
zeilenbereinigte Diagnose gespeichert; Zugangsdaten, Tokens und Tracebacks
werden nicht persistiert. Ein Scheduler ist ausdrücklich nicht Teil dieser
Phase.

### Investment Decision Copilot - Phase B

Phase B enthält ausschließlich den LLM-freien, deterministischen Kern des
Investment Decision Copilots. Er baut auf bestehenden Facts, Sources, DCF-,
Multiples-, Risiko-, Szenario-, Thesis- und Earnings-Daten auf und erzeugt ein
strukturiertes `InvestmentDecisionBrief`.

Die neutralen Kategorien sind `ATTRACTIVE`, `WATCH`, `CAUTION`,
`REVIEW_THESIS` und `INSUFFICIENT_DATA`. Confidence beschreibt die Qualität
und Konsistenz der Evidenz, nicht die Wahrscheinlichkeit zukünftiger Renditen.
Jede Evidence-Aussage muss auf vorhandene Fact-IDs und SourceRefs zeigen.

Diese Phase enthält bewusst noch keinen Ollama-Aufruf, keine API-Erweiterung,
keine Frontend-Änderung und keine neue Copilot-History. Die historische
Vergleichsstruktur ist als Domain-/Engine-Eingabe vorbereitet.

### Manueller End-to-End-Test

Für einen vollständigen lokalen Test öffne zwei PowerShell-Fenster. Das erste
startet die Infrastruktur und legt das Schema an:

```powershell
docker compose up -d
docker compose ps
alembic upgrade head
```

In `.env` muss für den SEC-Zugriff ein echter identifizierender User-Agent mit
Kontaktadresse gesetzt sein. Im zweiten Fenster:

```powershell
.\.venv\Scripts\python.exe -m app.cli analyze AAPL --skip-market-data --output reports/AAPL.md --save
.\.venv\Scripts\python.exe -m app.cli runs --ticker AAPL
```

Die Ausgabe von `runs` enthält die Laufkennung. Mit ihr kann der gespeicherte
Report geprüft werden:

```powershell
.\.venv\Scripts\python.exe -m app.cli report <lauf-kennung>
```

Für den Marktdatenpfad anschließend einen Lauf ohne `--skip-market-data` und
für den lokalen LLM-Pfad einen Lauf mit `--research` starten. Der LLM-Lauf kann
auf einer CPU mehrere Minuten dauern:

```powershell
docker exec finance_agents_llm ollama list
.\.venv\Scripts\python.exe -m app.cli analyze AAPL --research --save
```

Die API lässt sich separat prüfen, während `uvicorn` läuft:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --reload

Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/runs
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/watchlist `
  -ContentType 'application/json' `
  -Body '{"ticker":"AAPL","company_name":"Apple Inc.","notes":"Manueller Test"}'
Invoke-RestMethod http://127.0.0.1:8000/api/v1/watchlist
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/alerts?ticker=AAPL&threshold=0'
```

Die automatisierte lokale Prüfung bleibt der schnellste erste Check:

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not integration" -q
```

### Qualitative Einordnung mit lokalem Sprachmodell

Das Sprachmodell läuft lokal in Docker und kostet nichts. Einmalig starten und
das Modell laden:

```powershell
docker compose up -d ollama
docker exec finance_agents_llm ollama pull qwen2.5:7b-instruct
```

Danach:

```powershell
finance-agents analyze AAPL --research
```

Das Modell bekommt ausschließlich die bereits belegten Kennzahlen als
nummerierte Faktenliste und formuliert daraus Beobachtungen. Es liefert keine
eigenen Zahlen: Jede Aussage muss die Kennungen der genutzten Fakten nennen,
und jede Zahl im Satz muss aus genau diesen Fakten stammen. Aussagen, die diese
Prüfung nicht bestehen, werden verworfen und im Report als verworfen ausgewiesen.
Ist das Modell nicht erreichbar, entsteht lediglich ein Hinweis, der Report wird
trotzdem erzeugt.

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
migrations/        Alembic-Migrationen
tests/
```

## Status

Projekt im Aufbau.

- [x] Fundament: Konfiguration, Domänenmodelle mit Provenance
- [x] Infrastruktur: HTTP-Client, Cache, Rate-Limiter, Budgetkontrolle
- [x] Ports: austauschbare Provider-Interfaces
- [x] SEC-EDGAR-Adapter: Fundamentaldaten aus XBRL
- [x] Marktdaten-Adapter (Yahoo Finance) und Kennzahlen-Service
- [x] Bewertung: DCF mit Sensitivitätsmatrix, Multiples
- [x] Analyse-Orchestrierung, Markdown-Report, CLI
- [x] Persistenz: gespeicherte Läufe mit Kennzahlen, Quellen und Report
- [x] Research-Agent mit lokalem Sprachmodell (Ollama) und Belegpflicht
- [x] Risiko-, Wettbewerbs-, Szenarien- und finaler Research-Agent
- [x] FastAPI für Läufe, Historie, Diffs, Alerts und Watchlist
- [x] Read-only-Broker-Domäne, versionierter Fixture-Adapter und idempotente Persistenz
- [ ] Mapping eines anonymisierten echten Trade-Republic-Exports
- [x] Read-only-Portfolio-API
- [x] Persönliches React/TypeScript/Vite-Frontend mit Dashboard, Portfolio, Watchlist und Historie
- [x] Frontend-Stock-Detailseite mit strukturierten Financials, Valuation und Quellen
- [x] Strukturierte Persistenz und Frontend-Darstellung für Risiken und Szenarien
- [x] Analyse-Job-Endpunkt und Frontend-Startstatus
- [x] Frontend-Catalyst-Darstellung und Job-Status-Polling
- [ ] Produktiver Scheduler und langlebige Job-Persistenz
- [ ] Authentifizierung und Benutzerverwaltung für einen produktiven API-Betrieb

Integrationstests gegen die echte SEC-API laufen separat:

```powershell
pytest -m integration
```

