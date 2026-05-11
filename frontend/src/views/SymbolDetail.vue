<script setup lang="ts">
import { onMounted, ref, watch, computed, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NCard, NSpace, NTag, NText, NDataTable, NButton, NIcon, NSkeleton,
  NDescriptions, NDescriptionsItem, useMessage, NEmpty, NTime, NTooltip,
  NDivider, NBackTop
} from 'naive-ui'
import {
  ArrowBackOutline, RefreshOutline, CloudDownloadOutline, OpenOutline
} from '@vicons/ionicons5'
import { api, type SymbolDetail, AuthRequired } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import KLineChart from '@/components/KLineChart.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const message = useMessage()

const data = ref<SymbolDetail | null>(null)
const loading = ref(true)
const fetching = ref(false)
const loadingMore = ref(false)
const currentLimit = ref(800)

const market = computed(() => route.params.market as string)
const symbol = computed(() => route.params.symbol as string)

async function load(limit = 800) {
  loading.value = true
  try {
    const r = await api.get<SymbolDetail>(`/symbols/${market.value}/${symbol.value}`, {
      params: { limit }
    })
    data.value = r.data
    currentLimit.value = limit
  } catch (e) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else message.error('加载详情失败')
  } finally {
    loading.value = false
  }
}

async function loadAll() {
  loadingMore.value = true
  await load(10000)
  loadingMore.value = false
  message.success(`已加载全部 ${data.value?.candles.length ?? 0} 个交易日`)
}

async function refetch() {
  fetching.value = true
  try {
    await api.post('/data/fetch', {
      symbols: [{ market: market.value, symbol: symbol.value }]
    })
    message.success('已增量拉取')
    await load()
  } catch (e) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else message.error('拉取失败')
  } finally {
    fetching.value = false
  }
}

onMounted(load)
watch(() => [market.value, symbol.value], load)

function fmtNum(n: number) { return n.toLocaleString('en-US') }
function fmtPct(x: number) { return (x > 0 ? '+' : '') + x.toFixed(2) + '%' }

const summary = computed(() => {
  if (!data.value || data.value.candles.length === 0) return null
  const cs = data.value.candles
  const last = cs[cs.length - 1]
  const prev = cs.length > 1 ? cs[cs.length - 2] : last
  const chg = ((last.close - prev.close) / prev.close) * 100
  const high = Math.max(...cs.map(c => c.close))
  const low = Math.min(...cs.map(c => c.close))
  const totalReturn = ((last.close - cs[0].close) / cs[0].close) * 100
  return { last, prev, chg, high, low, totalReturn, count: cs.length }
})

// 涨跌色（A 股反着）
const colorChg = computed(() => {
  if (!summary.value) return ''
  const positive = summary.value.chg >= 0
  if (market.value === 'cn') return positive ? 'up' : 'down'
  return positive ? 'down-us' : 'up-us'  // US: green up
})

const candleColumns = [
  { title: '日期', key: 'date', width: 110, render: (r: any) => h('span', { class: 'mono' }, r.date) },
  {
    title: '开', key: 'open', align: 'right' as const,
    render: (r: any) => h('span', { class: 'mono' }, r.open.toFixed(2))
  },
  {
    title: '高', key: 'high', align: 'right' as const,
    render: (r: any) => h('span', { class: 'mono', style: 'color: var(--danger)' }, r.high.toFixed(2))
  },
  {
    title: '低', key: 'low', align: 'right' as const,
    render: (r: any) => h('span', { class: 'mono', style: 'color: var(--success)' }, r.low.toFixed(2))
  },
  {
    title: '收', key: 'close', align: 'right' as const,
    render: (r: any) => h('span', { class: 'mono', style: 'font-weight: 600' }, r.close.toFixed(2))
  },
  {
    title: '量', key: 'volume', align: 'right' as const,
    render: (r: any) => h('span', { class: 'mono muted', style: 'font-size: 12px' }, fmtNum(r.volume))
  },
  {
    title: '额', key: 'amount', align: 'right' as const,
    render: (r: any) => h('span', { class: 'mono muted', style: 'font-size: 12px' },
      r.amount.toLocaleString('en-US', { maximumFractionDigits: 0 }))
  },
]

const reversedCandles = computed(() => {
  if (!data.value) return []
  return [...data.value.candles].reverse().slice(0, 200)
})
</script>

<template>
  <div>
    <!-- Page Header -->
    <div class="page-head">
      <NButton text @click="router.back()" style="margin-right: 4px">
        <template #icon><NIcon><ArrowBackOutline /></NIcon></template>
      </NButton>
      <NTag :type="market === 'cn' ? 'error' : 'info'" :bordered="false" size="medium">
        {{ market.toUpperCase() }}
      </NTag>
      <h1 class="symbol-title mono">{{ symbol }}</h1>
      <NText depth="2" v-if="data?.meta?.name" style="font-size: 16px">
        · {{ data.meta.name }}
      </NText>
      <div style="flex: 1" />
      <NButton :loading="fetching" type="primary" @click="refetch">
        <template #icon><NIcon><CloudDownloadOutline /></NIcon></template>
        增量拉取
      </NButton>
    </div>

    <!-- Summary Bar -->
    <NCard class="summary-bar" v-if="summary" :bordered="false" content-style="padding: 22px 26px">
      <div class="summary-grid">
        <div>
          <div class="metric-label">最新收盘</div>
          <div class="metric-value mono gradient-text">{{ summary.last.close.toFixed(2) }}</div>
          <div class="muted mono" style="font-size: 11px">{{ summary.last.date }}</div>
        </div>
        <div class="metric-divider" />
        <div>
          <div class="metric-label">日涨跌</div>
          <div class="metric-value mono" :class="colorChg">{{ fmtPct(summary.chg) }}</div>
          <div class="muted mono" style="font-size: 11px">vs {{ summary.prev.close.toFixed(2) }}</div>
        </div>
        <div class="metric-divider" />
        <div>
          <div class="metric-label">区间收益</div>
          <div class="metric-value mono"
            :class="summary.totalReturn >= 0 ? (market === 'cn' ? 'up' : 'down-us') : (market === 'cn' ? 'down' : 'up-us')">
            {{ fmtPct(summary.totalReturn) }}
          </div>
          <div class="muted mono" style="font-size: 11px">{{ summary.count }} 个交易日</div>
        </div>
        <div class="metric-divider" />
        <div>
          <div class="metric-label">区间最高</div>
          <div class="metric-value mono">{{ summary.high.toFixed(2) }}</div>
        </div>
        <div class="metric-divider" />
        <div>
          <div class="metric-label">区间最低</div>
          <div class="metric-value mono">{{ summary.low.toFixed(2) }}</div>
        </div>
      </div>
    </NCard>
    <NSkeleton v-else-if="loading" height="120" style="margin: 20px 0" :sharp="false" />

    <!-- K 线 -->
    <NCard title="K 线" style="margin-top: 20px">
      <template #header-extra>
        <NSpace align="center" :size="8">
          <NText depth="3" class="mono" style="font-size: 12px">
            显示 {{ data?.candles.length ?? 0 }} 个交易日
          </NText>
          <NButton v-if="data && data.candles.length >= currentLimit && data.stats.rows > currentLimit"
            size="tiny" tertiary :loading="loadingMore" @click="loadAll">
            加载全部
          </NButton>
        </NSpace>
      </template>
      <KLineChart v-if="data && data.candles.length > 0"
        :candles="data.candles" :symbol="symbol" :market="market" />
      <NEmpty v-else-if="!loading" description="暂无行情数据" style="padding: 60px 0">
        <template #extra>
          <NButton type="primary" :loading="fetching" @click="refetch">立即拉取</NButton>
        </template>
      </NEmpty>
      <NSkeleton v-else height="480" :sharp="false" />
    </NCard>

    <!-- 元信息 + 最新数据表 -->
    <div class="detail-row" v-if="data">
      <NCard title="元信息" class="meta-card">
        <NDescriptions :column="1" label-placement="left" size="small">
          <NDescriptionsItem label="名称">{{ data.meta?.name || '-' }}</NDescriptionsItem>
          <NDescriptionsItem label="上市日">
            <span class="mono">{{ data.meta?.list_date || '-' }}</span>
          </NDescriptionsItem>
          <NDescriptionsItem label="状态">{{ data.meta?.status || '-' }}</NDescriptionsItem>
          <NDescriptionsItem label="数据起止">
            <span class="mono" style="font-size: 12px">
              {{ data.stats.min_date || '-' }} ~ {{ data.stats.max_date || '-' }}
            </span>
          </NDescriptionsItem>
          <NDescriptionsItem label="行数">
            <span class="mono">{{ (data.stats.rows ?? 0).toLocaleString() }}</span>
          </NDescriptionsItem>
          <NDescriptionsItem label="文件大小">
            <span class="mono">{{ data.stats.size_bytes ? (data.stats.size_bytes / 1024).toFixed(1) + ' KB' : '-' }}</span>
          </NDescriptionsItem>
          <NDescriptionsItem label="最近抓取">
            <NTime v-if="data.meta?.last_fetched_at"
              :time="new Date(data.meta.last_fetched_at)" type="relative" />
            <span v-else>-</span>
          </NDescriptionsItem>
        </NDescriptions>
      </NCard>

      <NCard title="最近 200 个交易日" class="table-card">
        <NDataTable :columns="candleColumns" :data="reversedCandles"
          :pagination="{ pageSize: 20 }" size="small" :bordered="false" :striped="true" />
      </NCard>
    </div>
    <NBackTop :right="32" :bottom="32" />
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.symbol-title {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin: 0;
}

.summary-bar {
  margin-top: 20px;
  background: linear-gradient(135deg, rgba(124,58,237,0.06), rgba(6,182,212,0.03)) !important;
  border: 1px solid rgba(124, 58, 237, 0.15) !important;
}
.summary-grid {
  display: grid;
  grid-template-columns: 1fr 1px 1fr 1px 1fr 1px 1fr 1px 1fr;
  align-items: center;
  gap: 24px;
}
.metric-label {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  font-weight: 500;
}
.metric-value {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin: 6px 0 2px;
  line-height: 1;
}
.metric-divider {
  width: 1px;
  height: 36px;
  background: var(--border-soft);
}

.detail-row {
  display: flex;
  gap: 16px;
  margin-top: 20px;
}
.meta-card {
  flex: 0 0 360px;
}
.table-card {
  flex: 1;
  min-width: 0;
}
</style>
