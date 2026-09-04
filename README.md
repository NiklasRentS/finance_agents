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
- [ ] Weitere Agenten (Filings, Risiko, Szenarien), API

Integrationstests gegen die echte SEC-API laufen separat:

```powershell
pytest -m integration
```

