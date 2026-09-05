export type Run = {
  id: string
  ticker: string
  company_name: string
  generated_at: string
  currency?: string | null
  period_label?: string | null
  value_per_share?: number | null
}

export type WatchlistItem = {
  id: string
  ticker: string
  company_name: string
  notes?: string | null
}

export type Position = {
  account_identifier: string
  broker: string
  isin: string
  ticker?: string | null
  name: string
  instrument_currency: string
  quantity: string | number
  average_cost: string | number
  current_value: string | number
  currency: string
  imported_at: string
}

export type CashBalance = {
  amount: string | number
  currency: string
}

export type Alert = {
  metric: string
  percent_change?: number | null
  delta?: number | null
}
export type DecisionEvidence = { evidence_id: string; category: string; statement: string; supporting_fact_ids: string[] }
export type DecisionBrief = {
  ticker: string
  company_name: string
  generated_at: string
  decision: 'ATTRACTIVE' | 'WATCH' | 'CAUTION' | 'REVIEW_THESIS' | 'INSUFFICIENT_DATA'
  confidence: 'HIGH' | 'MEDIUM' | 'LOW'
  confidence_reason: string
  summary: string
  why: string
  investment_thesis?: string | null
  positive_factors: string[]
  negative_factors: string[]
  key_risks: string[]
  valuation_summary: Record<string, unknown>
  key_uncertainties: string[]
  thesis_improvers: string[]
  thesis_deteriorators: string[]
  monitoring_points: string[]
  beginner_explanation: { explanation: string; why_it_matters: string; key_terms: Record<string, string> }
  evidence: DecisionEvidence[]
  analysis_run_id?: string | null
}
export type DecisionExplanation = DecisionBrief & {
  headline: string
  why_this_matters: string
  valuation_explanation: string
  uncertainty: string
  what_to_watch: string[]
  disclaimer: string
  model_metadata: Record<string, unknown>
}
export type AnalysisJob = { id: string; ticker: string; status: string; created_at: string; run_id?: string | null; error?: string | null }

export type ResearchFact = { value?: string | number | null; unit?: string | null }
export type ResearchStock = {
  run_id: string
  ticker: string
  company_name: string
  generated_at: string
  currency?: string | null
  assumptions: Record<string, unknown>
  valuation: Record<string, unknown>
  market?: Record<string, unknown> | null
  warnings: string[]
  risk_signals: Array<{ name: string; score: number; summary: string }>
  competitive?: { score: number; summary: string } | null
  scenarios: Array<{ name: string; probability: number; narrative: string }>
  thesis?: string | null
  catalysts: Array<{ name: string; summary: string }>
  decision_brief?: DecisionBrief | null
  financials: Array<{ period: { label?: string }; values: Record<string, ResearchFact> }>
  sources: string[]
  report_available: boolean
}

export type Portfolio = {
  positions: Position[]
  cash: CashBalance[]
}

const apiBase = import.meta.env.VITE_API_BASE ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, init)
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  runs: () => request<Run[]>('/api/v1/runs'),
  watchlist: () => request<WatchlistItem[]>('/api/v1/watchlist'),
  portfolio: () => request<Portfolio>('/api/v1/portfolio'),
  alerts: (ticker: string) => request<{ alerts: Alert[] }>(`/api/v1/alerts?ticker=${encodeURIComponent(ticker)}&threshold=0.1`),
  stock: (ticker: string) => request<ResearchStock>(`/api/v1/stocks/${encodeURIComponent(ticker)}`),
  decisionExplanation: (ticker: string) => request<DecisionExplanation>(`/api/v1/stocks/${encodeURIComponent(ticker)}/decision/explanation`, { method: 'POST' }),
  startAnalysis: async (ticker: string) => {
    const response = await fetch(`${apiBase}/api/v1/analysis`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticker }) })
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
    return response.json() as Promise<AnalysisJob>
  },
  analysisStatus: (jobId: string) => request<AnalysisJob>(`/api/v1/analysis/${encodeURIComponent(jobId)}`),
}
