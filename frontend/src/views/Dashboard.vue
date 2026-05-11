<script setup lang="ts">
import { onActivated, onMounted, ref, computed, h } from 'vue'
import { useRouter } from 'vue-router'
import {
  NSpace, NGrid, NGi, NCard, NSkeleton, NTag, NText, NDivider,
  NButton, NIcon, NDataTable, NTime, NEmpty, useMessage
} from 'naive-ui'
import {
  FileTrayFullOutline, ServerOutline, CalendarOutline, SwapHorizontalOutline,
  RefreshOutline, ArrowForwardOutline, FlashOutline, TrendingUpOutline
} from '@vicons/ionicons5'
import { type OverviewResp, AuthRequired } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useDataStore } from '@/stores/data'
import StatCard from '@/components/StatCard.vue'
import Sparkline from '@/components/Sparkline.vue'

const router = useRouter()
const auth = useAuthStore()
const message = useMessage()
const store = useDataStore()
const loading = ref(true)
const data = ref<OverviewResp | null>(null)
const marketSparks = ref<Record<string, number[]>>({})

async function load(forceReload = false) {
  loading.value = true
  try {
    const [overview, sparkMap] = await Promise.all([
      store.getOverview(forceReload),
      store.getSparklines(null, 60, forceReload),
    ])
    data.value = overview
    // 每个市场取第一只 cached symbol 的 sparkline 作为代表
    for (const m of overview.markets) {
      const symbolsForMarket = Object.keys(sparkMap).filter(k => k.startsWith(`${m.code}/`))
      if (symbolsForMarket.length > 0) {
        marketSparks.value[m.code] = sparkMap[symbolsForMarket[0]]
      }
    }
  } catch (e) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else message.error('加载概览失败')
  } finally {
    loading.value = false
  }
}
onMounted(() => load(false))
onActivated(() => load(false))

function fmtSize(bytes: number) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

const totalSize = computed(() => {
  if (!data.value) return 0
  return Object.values(data.value.cache).reduce((s, c) => s + c.size_bytes, 0)
})
const totalRows = computed(() => data.value?.db.rows_total ?? 0)

const marketCols = [
  {
    title: '市场',
    key: 'label',
    width: 110,
    render: (row: any) => h('div', { class: 'market-cell' }, [
      h(NTag, {
        type: row.code === 'cn' ? 'error' : 'info', size: 'small', bordered: false
      }, () => row.label),
      h('code', { class: 'mono muted', style: 'font-size: 11px; margin-left: 8px' }, row.code)
    ])
  },
  {
    title: '币种',
    key: 'currency',
    width: 70,
    render: (r: any) => h('span', { class: 'mono muted', style: 'font-size: 12px' }, r.currency)
  },
  {
    title: 'symbols',
    key: 'symbols_count',
    render: (r: any) => h('span', { class: 'mono', style: 'font-weight: 600' }, r.symbols_count)
  },
  {
    title: '总行数',
    key: 'rows_count',
    render: (r: any) => h('span', { class: 'mono' }, (r.rows_count || 0).toLocaleString())
  },
  {
    title: '交易日',
    key: 'calendar_count',
    render: (r: any) => h('span', { class: 'mono muted' }, r.calendar_count)
  },
  {
    title: '缓存',
    key: 'cache',
    render: (r: any) =>
      h('span', { class: 'mono' }, `${r.cache.files} 文件 · ${fmtSize(r.cache.size_bytes)}`)
  },
  {
    title: '',
    key: 'action',
    width: 130,
    render: (r: any) => h(NButton, {
      text: true, type: 'primary', size: 'small',
      onClick: () => router.push({ name: 'symbols', query: { market: r.code } })
    }, () => [h('span', null, '查看'), h(NIcon, { style: 'margin-left: 4px' }, () => h(ArrowForwardOutline))])
  }
]
</script>

<template>
  <div>
    <!-- 头部欢迎区 -->
    <div class="hero">
      <div class="hero-title">
        <span class="muted" style="font-size: 12px; letter-spacing: 0.18em">DASHBOARD</span>
        <h1>
          <span class="gradient-text">{{ auth.username }}</span>
          <span class="muted">，欢迎回来</span>
        </h1>
        <div class="muted" style="font-size: 13px">
          双市场量化数据平台 · A 股 + 美股 · 数据自 2018-01-01
        </div>
      </div>
      <NButton secondary size="small" @click="load(true)" :loading="loading">
        <template #icon><NIcon><RefreshOutline /></NIcon></template>
        刷新数据
      </NButton>
    </div>

    <!-- KPI 卡片（4 张）-->
    <NGrid :cols="4" :x-gap="16" :y-gap="16" responsive="screen" item-responsive style="margin-top: 24px">
      <NGi span="4 m:1">
        <NSkeleton v-if="loading && !data" height="110" :sharp="false" />
        <StatCard v-else
          label="SYMBOLS"
          :value="data?.db.symbols_total ?? 0"
          :icon="FileTrayFullOutline"
          color="#7c3aed"
          hero
          :hint="data ? Object.entries(data.db.symbols_by_market).map(([k,v]:any) => `${k.toUpperCase()} ${v.symbols}`).join(' · ') : ''"
        />
      </NGi>
      <NGi span="4 m:1">
        <NSkeleton v-if="loading && !data" height="110" :sharp="false" />
        <StatCard v-else
          label="ROWS"
          :value="totalRows"
          :icon="FlashOutline"
          color="#06b6d4"
          hero
          hint="总 OHLCV 数据点"
        />
      </NGi>
      <NGi span="4 m:1">
        <NSkeleton v-if="loading && !data" height="110" :sharp="false" />
        <StatCard v-else
          label="CACHE"
          :value="(totalSize / 1024 / 1024).toFixed(2)"
          :icon="ServerOutline"
          color="#10b981"
          hero
          suffix="MB"
          :hint="`${data ? Object.values(data.cache).reduce((s,c) => s + c.files, 0) : 0} 个 Parquet 文件`"
        />
      </NGi>
      <NGi span="4 m:1">
        <NSkeleton v-if="loading && !data" height="110" :sharp="false" />
        <StatCard v-else
          label="TRADING DAYS"
          :value="data?.db.calendar_total ?? 0"
          :icon="CalendarOutline"
          color="#f59e0b"
          hero
          :hint="data ? Object.entries(data.db.calendar_by_market).map(([k,v]) => `${k.toUpperCase()} ${v}`).join(' · ') : ''"
        />
      </NGi>
    </NGrid>

    <!-- 市场卡片（带 sparkline）-->
    <h2 class="section-title">市场快照</h2>
    <NGrid :cols="2" :x-gap="16" :y-gap="16" responsive="screen" item-responsive>
      <NGi v-for="m in (data?.markets ?? [])" :key="m.code" span="2 l:1">
        <NCard class="market-card" hoverable>
          <div class="market-card-row">
            <div class="market-card-meta">
              <NSpace align="center" :size="10">
                <NTag :type="m.code === 'cn' ? 'error' : 'info'" :bordered="false" size="medium">
                  {{ m.label }}
                </NTag>
                <NText depth="3" class="mono" style="font-size: 12px">{{ m.currency }}</NText>
              </NSpace>
              <div class="market-card-stats">
                <div>
                  <div class="muted" style="font-size: 11px; letter-spacing: 0.08em">SYMBOLS</div>
                  <div class="mono big-num">{{ m.symbols_count }}</div>
                </div>
                <div>
                  <div class="muted" style="font-size: 11px; letter-spacing: 0.08em">ROWS</div>
                  <div class="mono big-num">{{ (m.rows_count || 0).toLocaleString() }}</div>
                </div>
                <div>
                  <div class="muted" style="font-size: 11px; letter-spacing: 0.08em">CACHE</div>
                  <div class="mono big-num">{{ fmtSize(m.cache.size_bytes) }}</div>
                </div>
              </div>
            </div>
            <div class="market-card-chart">
              <Sparkline v-if="marketSparks[m.code]"
                :data="marketSparks[m.code]" :market="m.code"
                :width="180" :height="64" />
            </div>
          </div>
          <NDivider style="margin: 16px 0 12px" />
          <NSpace justify="space-between" align="center">
            <NText depth="3" style="font-size: 12px">
              Universes: <span class="mono">{{ m.named_universes.join(', ') }}</span>
            </NText>
            <NButton size="small" tertiary
              @click="router.push({ name: 'symbols', query: { market: m.code } })">
              查看所有
              <template #icon><NIcon><ArrowForwardOutline /></NIcon></template>
            </NButton>
          </NSpace>
        </NCard>
      </NGi>
    </NGrid>

    <!-- 市场对比表 -->
    <h2 class="section-title">详细对比</h2>
    <NCard>
      <NDataTable v-if="data"
        :columns="marketCols" :data="data.markets" :bordered="false" :pagination="false" size="medium" />
      <NSkeleton v-else height="180" :sharp="false" />
    </NCard>

    <!-- 系统元信息 -->
    <h2 class="section-title">存储元信息</h2>
    <NGrid :cols="4" :x-gap="16" :y-gap="16" responsive="screen" item-responsive v-if="data">
      <NGi span="4 s:2 m:1">
        <NCard size="small">
          <div class="meta-label">SCHEMA VERSION</div>
          <div class="meta-value mono">v{{ data.meta.schema_version }}</div>
        </NCard>
      </NGi>
      <NGi span="4 s:2 m:1">
        <NCard size="small">
          <div class="meta-label">INITIAL_START_DATE</div>
          <div class="meta-value mono">{{ data.meta.initial_start_date }}</div>
        </NCard>
      </NGi>
      <NGi span="4 s:2 m:1">
        <NCard size="small">
          <div class="meta-label">压缩</div>
          <div class="meta-value mono">{{ data.meta.compression }}</div>
        </NCard>
      </NGi>
      <NGi span="4 s:2 m:1">
        <NCard size="small">
          <div class="meta-label">初始化于</div>
          <div class="meta-value mono">
            <NTime :time="new Date(data.meta.created_at)" format="yyyy-MM-dd HH:mm" />
          </div>
        </NCard>
      </NGi>
    </NGrid>
  </div>
</template>

<style scoped>
.hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
}
.hero-title h1 {
  margin: 6px 0 6px;
  font-size: 32px;
  font-weight: 700;
  letter-spacing: -0.025em;
  line-height: 1.1;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.005em;
  margin: 32px 0 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.section-title::before {
  content: '';
  width: 3px;
  height: 14px;
  background: linear-gradient(180deg, #7c3aed, #06b6d4);
  border-radius: 2px;
}

.market-card {
  transition: transform 0.18s ease;
}
.market-card:hover {
  transform: translateY(-2px);
}
.market-card-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}
.market-card-meta {
  flex: 1;
}
.market-card-stats {
  display: flex;
  gap: 32px;
  margin-top: 18px;
}
.market-card-chart {
  flex-shrink: 0;
}
.big-num {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-top: 2px;
}

.meta-label {
  font-size: 11px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  text-transform: uppercase;
}
.meta-value {
  font-size: 18px;
  font-weight: 600;
  margin-top: 6px;
  letter-spacing: -0.01em;
}

/* ─── 移动端 ─── */
@media (max-width: 768px) {
  .hero {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .hero-title h1 {
    font-size: 22px !important;
    margin-bottom: 0;
  }
  .section-title {
    margin: 20px 0 10px;
    font-size: 14px;
  }
  .market-card-row {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .market-card-stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin-top: 12px;
  }
  .big-num {
    font-size: 17px;
  }
  .market-card-chart {
    width: 100%;
    display: flex;
    justify-content: center;
  }
  .market-card-chart :deep(svg) {
    width: 100% !important;
    max-width: 280px;
    height: 56px;
  }
  .meta-value { font-size: 15px; }
  .meta-label { font-size: 10px; }
  /* 详细对比表强制 horizontal scroll */
  :deep(.n-data-table) {
    overflow-x: auto !important;
  }
  :deep(.n-data-table-wrapper) { min-width: 600px; }
}

.market-cell {
  display: flex;
  align-items: center;
}
</style>
