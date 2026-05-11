import axios, { type AxiosError, type AxiosInstance } from 'axios'

const STORAGE_KEY = 'quant-lite-auth'

interface AuthCreds {
  username: string
  password: string
}

function loadAuth(): AuthCreds | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
}

export function saveAuth(creds: AuthCreds) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(creds))
}

export function clearAuth() {
  localStorage.removeItem(STORAGE_KEY)
}

export function getCurrentAuthUsername(): string | null {
  return loadAuth()?.username ?? null
}

export const api: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 60_000
})

api.interceptors.request.use((config) => {
  const auth = loadAuth()
  if (auth) {
    const token = btoa(`${auth.username}:${auth.password}`)
    config.headers.Authorization = `Basic ${token}`
  }
  return config
})

export class AuthRequired extends Error {}

api.interceptors.response.use(
  (resp) => resp,
  (err: AxiosError) => {
    if (err.response?.status === 401) {
      clearAuth()
      return Promise.reject(new AuthRequired('Unauthorized'))
    }
    return Promise.reject(err)
  }
)

// ─── 类型定义 ────────────────────────────────────────────

export interface MarketInfo {
  code: string
  label: string
  currency: string
  cache: { files: number; size_bytes: number }
  symbols_count: number
  calendar_count: number
  named_universes: string[]
}

export interface OverviewResp {
  meta: {
    schema_version: number
    initial_start_date: string
    compression: string
    markets: string[]
    created_at: string
  }
  db: {
    symbols_total: number
    rows_total?: number
    size_bytes_total?: number
    symbols_by_market: Record<string, any>
    calendar_total: number
    calendar_by_market: Record<string, number>
    strategies_total: number
    backtests_total: number
  }
  cache: Record<string, { files: number; size_bytes: number; size_mb: number }>
  markets: MarketInfo[]
}

export interface SymbolRow {
  market: string
  symbol: string
  name: string
  list_date: string | null
  status: string
  last_fetched_at: string | null
  cached: boolean
  rows: number
  min_date: string | null
  max_date: string | null
  size_bytes: number
}

export interface Candle {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
}

export interface SymbolDetail {
  market: string
  symbol: string
  meta: SymbolRow | null
  stats: {
    cached: boolean
    rows: number
    min_date: string | null
    max_date: string | null
    size_bytes: number
  }
  candles: Candle[]
}

export interface FetchResult {
  market: string
  symbol: string
  status: string
  rows_added: number
  total_rows: number
  max_date: string | null
  error?: string
}

export interface FetchResp {
  triggered_by: string
  summary: { ok: number; errors: number; rows_added: number }
  results: FetchResult[]
}

export interface SparklineResp {
  market: string
  symbol: string
  closes: number[]
}

export async function fetchSparkline(market: string, symbol: string, days = 30): Promise<number[]> {
  const r = await api.get<SparklineResp>(`/symbols/${market}/${symbol}/sparkline`, {
    params: { days },
  })
  return r.data.closes
}

export interface ScheduleJob {
  id: string
  name?: string
  universe: string
  next_run: string | null
  last_run: {
    ts: string
    duration_s: number
    ok: number
    errors: number
    rows_added: number
    status: 'success' | 'partial' | 'error'
    error?: string
  } | null
}

export interface ScheduleResp {
  enabled: boolean
  tz: string
  jobs: ScheduleJob[]
}

// ─── 回测 ────────────────────────────────────────────────

export interface BacktestMetrics {
  cum_return: number
  annual_return: number
  annual_vol: number
  sharpe: number
  max_drawdown: number
  win_rate: number
}

export interface BacktestParams {
  universe: string
  top_n: number
  bottom_n?: number
  rebalance: string
  cost?: number
  start: string | null
  end: string | null
}

export interface BacktestResp {
  id: number | null
  strategy_id: number | null
  saved: boolean
  metrics: BacktestMetrics
  nav_curve: [string, number][]
  benchmark_curve: [string, number][]
  benchmark_metrics: BacktestMetrics
  excess_return: number
  rebalance_dates: string[]
  holdings_history: Record<string, string[]>
  params: BacktestParams
  duration_ms: number
  rows_used: number
  triggered_by: string
  total_cost?: number
}

export interface ValidateResp {
  ok: boolean
  error?: string
  line?: number
  col?: number
  factors?: string[]
  has_strategy?: boolean
  strategy?: {
    universe: string
    signal: string
    top_n: number
    rebalance: string
    start: string | null
    end: string | null
  } | null
}

export interface StrategyRow {
  id: number
  name: string
  dsl: string
  created_by: string
  created_at: string
  updated_at: string
}

export interface BacktestRow {
  id: number
  strategy_id: number | null
  strategy_name: string | null
  dsl: string
  params: BacktestParams
  metrics: BacktestMetrics
  duration_ms: number
  created_by: string
  created_at: string
}

// ─── AI ──────────────────────────────────────────────────

export interface AIModelView {
  id: string
  label: string
  format: 'openai' | 'anthropic'
  api_key_set: boolean
  api_key_masked: string
  model_id: string
  base_url: string
}

export interface AIConfigView {
  models: AIModelView[]
  default_model_id: string
}

export interface AIModelInput {
  id?: string
  label: string
  format: 'openai' | 'anthropic'
  api_key: string             // 留空或 '***' 表示保持原值
  model_id: string
  base_url: string
}

export interface AIConfigUpdate {
  models: AIModelInput[]
  default_model_id: string
}

export interface AIStatus {
  enabled: boolean
  default_model_id: string
  models: Array<{
    id: string
    label: string
    format: string
    model_id: string
    configured: boolean
  }>
}

export interface ToolCallLog {
  name: string
  input: any
  result: any
  iteration: number
}

export interface ChatResp {
  ok: boolean
  message?: string
  error?: string
  dsl?: string | null
  backtest_result?: any | null
  tool_calls: ToolCallLog[]
  model?: { id: string; label: string; model_id: string }
  duration_ms: number
  triggered_by?: string
}

// SSE 事件
export type ChatEvent =
  | { type: 'started'; model: { id: string; label: string; model_id: string; format: string } }
  | { type: 'thinking'; iteration: number }
  | { type: 'thinking_text'; text: string; iteration: number }
  | { type: 'tool_call_start'; id: string; name: string; input: any; iteration: number }
  | { type: 'tool_call_end'; id: string; name: string; result: any; iteration: number }
  | { type: 'final_message'; text: string }
  | { type: 'done'; result: ChatResp }
  | { type: 'error'; error: string }

export async function streamChat(
  params: { text: string; model_id?: string },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const authRaw = localStorage.getItem('quant-lite-auth')
  if (!authRaw) throw new AuthRequired()
  const auth = JSON.parse(authRaw)
  const token = btoa(`${auth.username}:${auth.password}`)

  const resp = await fetch('/api/ai/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Basic ${token}`,
    },
    body: JSON.stringify(params),
    signal,
  })

  if (resp.status === 401) throw new AuthRequired()
  if (!resp.ok) {
    const txt = await resp.text()
    throw new Error(`HTTP ${resp.status}: ${txt.slice(0, 300)}`)
  }
  if (!resp.body) throw new Error('No response body')

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const evt of events) {
      const lines = evt.split('\n').filter(l => l.startsWith('data: '))
      for (const line of lines) {
        try {
          const data = JSON.parse(line.slice(6)) as ChatEvent
          onEvent(data)
        } catch (e) {
          console.error('parse SSE event failed:', e, line)
        }
      }
    }
  }
}
