<script setup lang="ts">
import { onActivated, onMounted, ref, h, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  NCard, NDataTable, NTag, NSpace, NSelect, NInput, NButton, NIcon,
  NEmpty, NTime, useMessage
} from 'naive-ui'
import { RefreshOutline, SearchOutline, OpenOutline } from '@vicons/ionicons5'
import { type SymbolRow, AuthRequired } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useDataStore } from '@/stores/data'
import Sparkline from '@/components/Sparkline.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const message = useMessage()
const store = useDataStore()

const rows = ref<SymbolRow[]>([])
const sparks = ref<Record<string, number[]>>({})
const loading = ref(false)
const sparkLoading = ref(false)
const market = ref<string | null>((route.query.market as string) || null)
const search = ref('')

const marketOptions = [
  { label: '全部市场', value: null },
  { label: 'A 股 (CN)', value: 'cn' },
  { label: '美股 (US)', value: 'us' },
]

async function load(forceReload = false) {
  loading.value = true
  try {
    rows.value = await store.getSymbols(market.value, forceReload)
  } catch (e) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else message.error('加载 symbols 失败')
  } finally {
    loading.value = false
  }
  // sparkline 单独加载，不阻塞表格
  sparkLoading.value = true
  try {
    sparks.value = await store.getSparklines(market.value, 30, forceReload)
  } catch {
    // sparkline 失败不影响列表
  } finally {
    sparkLoading.value = false
  }
}

onMounted(() => load(false))
onActivated(() => load(false))  // keep-alive 时回到页面
watch(market, () => load(false))

const filtered = computed(() => {
  if (!search.value) return rows.value
  const s = search.value.toLowerCase()
  return rows.value.filter(
    r => r.symbol.toLowerCase().includes(s) || r.name.toLowerCase().includes(s)
  )
})

function fmtSize(bytes: number) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

const columns = [
  {
    title: '市场', key: 'market', width: 80,
    render: (r: SymbolRow) => h(NTag, {
      type: r.market === 'cn' ? 'error' : 'info', size: 'small', bordered: false
    }, () => r.market.toUpperCase())
  },
  {
    title: 'Symbol', key: 'symbol', width: 110,
    render: (r: SymbolRow) => h('code', { class: 'mono', style: 'font-weight: 600; font-size: 13px' }, r.symbol)
  },
  { title: '名称', key: 'name', minWidth: 180 },
  {
    title: '30 日走势', key: 'sparkline', width: 140,
    render: (r: SymbolRow) => {
      const data = sparks.value[`${r.market}/${r.symbol}`]
      if (!data) {
        return h('span', { class: 'muted', style: 'font-size: 11px' },
          sparkLoading.value ? '…' : '—')
      }
      return h(Sparkline, { data, market: r.market, width: 120, height: 36 })
    }
  },
  {
    title: '上市日', key: 'list_date', width: 100,
    render: (r: SymbolRow) => h('span', { class: 'muted mono', style: 'font-size: 12px' }, r.list_date || '-')
  },
  {
    title: '状态', key: 'status', width: 80,
    render: (r: SymbolRow) => h(NTag, {
      type: r.status === 'active' ? 'success' : 'default',
      size: 'small', bordered: false
    }, () => r.status)
  },
  {
    title: '缓存覆盖', key: 'cached', width: 220,
    render: (r: SymbolRow) => {
      if (!r.cached || !r.rows) {
        return h('span', { class: 'muted', style: 'font-size: 12px' }, '未缓存')
      }
      return h('div', { class: 'mono', style: 'font-size: 12px; line-height: 1.4' }, [
        h('div', null, `${r.min_date} → ${r.max_date}`),
        h('div', { class: 'muted' }, `${r.rows.toLocaleString()} 行 · ${fmtSize(r.size_bytes)}`)
      ])
    }
  },
  {
    title: '最近抓取', key: 'last_fetched_at', width: 150,
    render: (r: SymbolRow) => r.last_fetched_at
      ? h(NTime, { time: new Date(r.last_fetched_at), type: 'relative' })
      : h('span', { class: 'muted', style: 'font-size: 12px' }, '-')
  },
  {
    title: '', key: 'action', width: 90,
    render: (r: SymbolRow) => h(NButton, {
      text: true, type: 'primary', size: 'small',
      onClick: () => router.push({ name: 'symbol-detail', params: { market: r.market, symbol: r.symbol } })
    }, () => [h(NIcon, null, () => h(OpenOutline)), ' 详情'])
  }
]
</script>

<template>
  <NCard>
    <template #header>
      <div style="display: flex; align-items: center; gap: 12px">
        <span>股票列表</span>
        <span class="muted mono" style="font-size: 12px; font-weight: 400">
          {{ filtered.length }} / {{ rows.length }}
        </span>
      </div>
    </template>
    <template #header-extra>
      <NSpace>
        <NSelect v-model:value="market" :options="marketOptions" style="width: 150px" />
        <NInput v-model:value="search" placeholder="搜索 symbol / 名称" clearable style="width: 240px">
          <template #prefix>
            <NIcon><SearchOutline /></NIcon>
          </template>
        </NInput>
        <NButton @click="load(true)" :loading="loading">
          <template #icon><NIcon><RefreshOutline /></NIcon></template>
          刷新
        </NButton>
      </NSpace>
    </template>

    <NDataTable
      :columns="columns" :data="filtered" :loading="loading"
      :bordered="false" :pagination="{ pageSize: 20 }" :striped="true" size="small"
      :row-class-name="() => 'symbol-row'"
    />
    <NEmpty v-if="!loading && rows.length === 0"
      description="还没有 symbols。请先去『数据操作』拉数据" style="padding: 60px 0" />
  </NCard>
</template>

<style scoped>
:deep(.symbol-row) { height: 56px; }
:deep(.n-data-table-td) {
  padding-top: 8px;
  padding-bottom: 8px;
}
</style>
