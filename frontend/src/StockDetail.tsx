import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowUpRight, FileText, ShieldCheck } from 'lucide-react'
import { api, type ResearchStock } from './api'

type StockDetailProps = { ticker: string; onBack: () => void }

function valueOf(value: unknown) {
  if (typeof value === 'number') return value
  if (typeof value === 'string') return Number(value)
  return null
}

function display(value: unknown, unit?: string | null) {
  const numeric = valueOf(value)
  if (numeric === null || Number.isNaN(numeric)) return 'DATA NOT AVAILABLE'
  return `${numeric.toLocaleString('en-US', { maximumFractionDigits: 2 })}${unit ? ` ${unit}` : ''}`
}

export function StockDetail({ ticker, onBack }: StockDetailProps) {
  const [stock, setStock] = useState<ResearchStock | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    void api.stock(ticker).then((result) => {
      if (active) setStock(result)
    }).catch(() => {
      if (active) setError(`Keine gespeicherte Analyse für ${ticker} gefunden.`)
    })
    return () => { active = false }
  }, [ticker])

  if (error) return <section className="view-stack"><button className="text-button" onClick={onBack}><ArrowLeft size={15} /> Back to research</button><div className="detail-empty"><FileText size={24} /><strong>{error}</strong><span>Run an analysis from the CLI first, then refresh this view.</span></div></section>
  if (!stock) return <section className="detail-loading"><span className="status-dot" /> Loading structured research for {ticker}...</section>

  const latest = stock.financials[stock.financials.length - 1]
  const values = latest?.values ?? {}
  const valuation = stock.valuation as Record<string, unknown>
  const fairValue = (valuation.value_per_share as Record<string, unknown> | undefined)?.value

  return <section className="view-stack">
    <button className="text-button back-button" onClick={onBack}><ArrowLeft size={15} /> Back to research</button>
    <div className="detail-hero"><div><span className="section-kicker">STRUCTURED RESEARCH</span><h2>{stock.ticker} <span>{stock.company_name}</span></h2><p>Latest saved analysis · {new Date(stock.generated_at).toLocaleString('en-GB')}</p></div><span className="source-tag"><ShieldCheck size={12} /> Source-linked</span></div>
    {stock.warnings.length > 0 && <div className="notice"><FileText size={16} />{stock.warnings[0]}</div>}
    <div className="metric-grid detail-metrics"><Metric label="Fair value" value={display(fairValue, stock.currency ?? undefined)} /><Metric label="Revenue" value={display(values.revenue?.value, values.revenue?.unit)} /><Metric label="Free cash flow" value={display(values.free_cash_flow?.value, values.free_cash_flow?.unit)} /><Metric label="ROIC" value={display(values.roic?.value, '%')} /></div>
    <div className="detail-grid"><article className="panel"><div className="panel-heading"><div><span className="section-kicker">FINANCIALS</span><h2>Reported metrics</h2></div><span className="source-tag">{latest?.period.label ?? 'Latest period'}</span></div><div className="financial-list">{['revenue', 'revenue_growth', 'operating_margin', 'eps_diluted', 'free_cash_flow', 'roic', 'total_debt'].map((metric) => <div className="financial-row" key={metric}><span>{metric.split('_').join(' ')}</span><strong>{display(values[metric]?.value, values[metric]?.unit)}</strong></div>)}</div></article><article className="panel"><div className="panel-heading"><div><span className="section-kicker">VALUATION</span><h2>Model outputs</h2></div><ArrowUpRight size={17} className="muted-icon" /></div><div className="financial-list"><div className="financial-row"><span>Fair value / share</span><strong>{display(fairValue, stock.currency ?? undefined)}</strong></div><div className="financial-row"><span>Current price</span><strong>{display((stock.market?.quote as Record<string, unknown> | undefined)?.price && ((stock.market?.quote as Record<string, unknown>).price as Record<string, unknown>).value, stock.currency ?? undefined)}</strong></div><div className="financial-row"><span>WACC</span><strong>{display((stock.assumptions as Record<string, unknown>).wacc, '%')}</strong></div><div className="financial-row"><span>Terminal growth</span><strong>{display((stock.assumptions as Record<string, unknown>).terminal_growth, '%')}</strong></div></div><div className="detail-note">Model outputs are deterministic and remain tied to the saved assumptions.</div></article></div>
    <div className="detail-grid"><article className="panel"><div className="panel-heading"><div><span className="section-kicker">RISKS</span><h2>Observed signals</h2></div><ShieldCheck size={17} className="muted-icon" /></div><div className="insight-list">{stock.risk_signals.length ? stock.risk_signals.map((signal) => <div className="insight-row" key={signal.name}><div><strong>{signal.name}</strong><small>{signal.summary}</small></div><b>{signal.score.toFixed(0)}</b></div>) : <div className="empty-state">No structured risk signals available.</div>}</div></article><article className="panel"><div className="panel-heading"><div><span className="section-kicker">SCENARIOS</span><h2>Research framing</h2></div><span className="source-tag">No recommendation</span></div><div className="insight-list">{stock.scenarios.map((scenario) => <div className="insight-row" key={scenario.name}><div><strong>{scenario.name}</strong><small>{scenario.narrative}</small></div><b>{(scenario.probability * 100).toFixed(0)}%</b></div>)}</div></article></div>
    <article className="panel"><div className="panel-heading"><div><span className="section-kicker">SOURCES</span><h2>Evidence used in this run</h2></div><span>{stock.sources.length} sources</span></div><div className="source-list">{stock.sources.map((source) => <div key={source}><ShieldCheck size={14} />{source}</div>)}</div></article>
    <article className="research-strip"><div className="strip-icon"><FileText size={18} /></div><div><span className="section-kicker">RESEARCH REPORT</span><strong>{stock.report_available ? 'Human-readable report available' : 'No report saved for this run'}</strong><small>Open the report through the API without using it as a frontend data source.</small></div><button className="secondary-button"><ArrowUpRight size={15} /> Open report</button></article>
  </section>
}

function Metric({ label, value }: { label: string; value: string }) { return <article className="metric-card"><span>{label}</span><strong>{value}</strong><small>Latest structured value</small></article> }
