/** 前端缓存层：避免来回路由都重发请求。 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type OverviewResp, type SymbolRow } from '@/api/client'

const TTL_MS = 5 * 60 * 1000  // 5 分钟

interface Cached<T> {
  data: T
  ts: number
}

function fresh<T>(c: Cached<T> | null): T | null {
  if (!c) return null
  if (Date.now() - c.ts > TTL_MS) return null
  return c.data
}

export const useDataStore = defineStore('data', () => {
  const overviewCache = ref<Cached<OverviewResp> | null>(null)
  const symbolsCache = ref<Record<string, Cached<SymbolRow[]>>>({})
  const sparkCache = ref<Record<string, Cached<Record<string, number[]>>>>({})

  async function getOverview(forceReload = false): Promise<OverviewResp> {
    if (!forceReload) {
      const cached = fresh(overviewCache.value)
      if (cached) return cached
    }
    const r = await api.get<OverviewResp>('/overview')
    overviewCache.value = { data: r.data, ts: Date.now() }
    return r.data
  }

  async function getSymbols(market: string | null, forceReload = false): Promise<SymbolRow[]> {
    const key = market ?? '_all'
    if (!forceReload) {
      const cached = fresh(symbolsCache.value[key])
      if (cached) return cached
    }
    const params = market ? { market } : {}
    const r = await api.get<SymbolRow[]>('/symbols', { params })
    symbolsCache.value[key] = { data: r.data, ts: Date.now() }
    return r.data
  }

  async function getSparklines(market: string | null, days = 30, forceReload = false):
    Promise<Record<string, number[]>> {
    const key = `${market ?? '_all'}:${days}`
    if (!forceReload) {
      const cached = fresh(sparkCache.value[key])
      if (cached) return cached
    }
    const params: any = { days }
    if (market) params.market = market
    const r = await api.get<Array<{ market: string; symbol: string; closes: number[] }>>(
      '/sparklines', { params }
    )
    const map = Object.fromEntries(r.data.map(s => [`${s.market}/${s.symbol}`, s.closes]))
    sparkCache.value[key] = { data: map, ts: Date.now() }
    return map
  }

  function invalidate() {
    overviewCache.value = null
    symbolsCache.value = {}
    sparkCache.value = {}
  }

  return { getOverview, getSymbols, getSparklines, invalidate }
})
