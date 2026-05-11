<script setup lang="ts">
import { onActivated, onMounted, ref, h } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard, NDataTable, NSpace, NButton, NIcon, NTime, NText, NEmpty, NTag,
  NPopconfirm, useMessage
} from 'naive-ui'
import { EyeOutline, TrashOutline, RefreshOutline } from '@vicons/ionicons5'
import { api, type BacktestRow, AuthRequired } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const message = useMessage()

const rows = ref<BacktestRow[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const r = await api.get<BacktestRow[]>('/backtests')
    rows.value = r.data
  } catch (e) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else message.error('加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
onActivated(load)

async function del(id: number) {
  try {
    await api.delete(`/backtests/${id}`)
    message.success(`已删除 #${id}`)
    await load()
  } catch (e) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else message.error('删除失败')
  }
}

const columns = [
  {
    title: '#',
    key: 'id',
    width: 60,
    render: (r: BacktestRow) => h('span', { class: 'mono', style: 'font-weight: 600' }, '#' + r.id),
  },
  {
    title: '策略',
    key: 'strategy_name',
    width: 160,
    render: (r: BacktestRow) => r.strategy_name
      ? h('span', { class: 'mono' }, r.strategy_name)
      : h('span', { class: 'muted', style: 'font-style: italic' }, '即席'),
  },
  {
    title: 'Universe',
    key: 'universe',
    width: 130,
    render: (r: BacktestRow) => h(NTag, {
      type: r.params.universe?.startsWith('cn') ? 'error' : 'info',
      size: 'small', bordered: false,
    }, () => r.params.universe || '?'),
  },
  {
    title: '配置',
    key: 'cfg',
    width: 170,
    render: (r: BacktestRow) => h('span', { class: 'mono', style: 'font-size: 12px' },
      `top ${r.params.top_n} · ${r.params.rebalance}`),
  },
  {
    title: '累计',
    key: 'cum',
    width: 100,
    align: 'right' as const,
    render: (r: BacktestRow) => {
      const v = r.metrics.cum_return
      const color = v >= 0 ? '#10b981' : '#ef4444'
      const sign = v >= 0 ? '+' : ''
      return h('span', { class: 'mono', style: `color: ${color}; font-weight: 600` },
        sign + (v * 100).toFixed(2) + '%')
    },
  },
  {
    title: '夏普',
    key: 'sharpe',
    width: 80,
    align: 'right' as const,
    render: (r: BacktestRow) => h('span', { class: 'mono' }, r.metrics.sharpe.toFixed(2)),
  },
  {
    title: '回撤',
    key: 'mdd',
    width: 80,
    align: 'right' as const,
    render: (r: BacktestRow) => h('span', { class: 'mono', style: 'color: #ef4444' },
      '-' + (r.metrics.max_drawdown * 100).toFixed(2) + '%'),
  },
  {
    title: '创建人',
    key: 'created_by',
    width: 100,
    render: (r: BacktestRow) => h('span', { style: 'font-size: 13px' }, r.created_by),
  },
  {
    title: '时间',
    key: 'created_at',
    width: 130,
    render: (r: BacktestRow) => h(NTime, {
      time: new Date(r.created_at + 'Z'), type: 'relative',
    }),
  },
  {
    title: '',
    key: 'action',
    width: 110,
    render: (r: BacktestRow) => h(NSpace, { size: 4 }, () => [
      h(NButton, {
        text: true, type: 'primary', size: 'small',
        onClick: () => router.push({ name: 'lab', query: { backtest_id: r.id } }),
      }, () => [h(NIcon, null, () => h(EyeOutline)), ' 查看']),
      h(NPopconfirm, {
        onPositiveClick: () => del(r.id),
      }, {
        trigger: () => h(NButton, { text: true, type: 'error', size: 'small' },
          () => [h(NIcon, null, () => h(TrashOutline))]),
        default: () => `确定删除回测 #${r.id}？`,
      }),
    ]),
  },
]
</script>

<template>
  <NCard>
    <template #header>
      <NSpace align="center" :size="10">
        <span>回测历史</span>
        <NText depth="3" class="mono" style="font-size: 12px; font-weight: 400">
          最近 {{ rows.length }} 次
        </NText>
      </NSpace>
    </template>
    <template #header-extra>
      <NButton @click="load">
        <template #icon><NIcon><RefreshOutline /></NIcon></template>
        刷新
      </NButton>
    </template>
    <!-- 桌面：表格 -->
    <div class="desktop-only">
      <NDataTable :columns="columns" :data="rows" :loading="loading"
        :bordered="false" :pagination="{ pageSize: 30 }" size="small" :striped="true" />
    </div>

    <!-- 移动：卡片列表 -->
    <div class="mobile-only bt-cards">
      <div v-for="r in rows" :key="r.id" class="bt-card"
        @click="router.push({ name: 'lab', query: { backtest_id: r.id } })">
        <div class="bt-head">
          <span class="mono bt-id">#{{ r.id }}</span>
          <NTag :type="r.params.universe?.startsWith('cn') ? 'error' : 'info'"
            size="small" :bordered="false">
            {{ r.params.universe || '?' }}
          </NTag>
          <span class="mono bt-cfg">
            top {{ r.params.top_n }}{{ r.params.bottom_n ? `/bot ${r.params.bottom_n}` : '' }}
            · {{ r.params.rebalance }}
          </span>
        </div>
        <div class="bt-name mono" v-if="r.strategy_name">{{ r.strategy_name }}</div>
        <div class="bt-name muted" style="font-style: italic" v-else>即席回测</div>
        <div class="bt-metrics">
          <div class="bt-metric">
            <div class="muted bt-mlabel">累计</div>
            <div class="mono bt-mvalue" :class="r.metrics.cum_return >= 0 ? 'up' : 'down'">
              {{ r.metrics.cum_return >= 0 ? '+' : '' }}{{ (r.metrics.cum_return * 100).toFixed(2) }}%
            </div>
          </div>
          <div class="bt-metric">
            <div class="muted bt-mlabel">夏普</div>
            <div class="mono bt-mvalue">{{ r.metrics.sharpe.toFixed(2) }}</div>
          </div>
          <div class="bt-metric">
            <div class="muted bt-mlabel">回撤</div>
            <div class="mono bt-mvalue down">−{{ (r.metrics.max_drawdown * 100).toFixed(2) }}%</div>
          </div>
        </div>
        <div class="bt-foot muted">
          <span>{{ r.created_by }}</span>
          <span>·</span>
          <NTime :time="new Date(r.created_at + 'Z')" type="relative" />
        </div>
      </div>
    </div>

    <NEmpty v-if="!loading && rows.length === 0"
      description="还没有回测记录。去「策略实验室」点「保存策略」会留下一条。"
      style="padding: 60px 0" />
  </NCard>
</template>

<style scoped>
.desktop-only { display: block; }
.mobile-only { display: none; }
@media (max-width: 768px) {
  .desktop-only { display: none; }
  .mobile-only { display: block; }
  :deep(.n-card-header) { flex-wrap: wrap; gap: 8px !important; }
  :deep(.n-card-header__extra) { width: 100%; }
  :deep(.n-card-header__extra .n-button) { width: 100%; }
}

.bt-cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.bt-card {
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--surface-1);
  border: 1px solid var(--border-soft);
  cursor: pointer;
  transition: border-color 0.15s ease, transform 0.15s ease;
}
.bt-card:active {
  transform: scale(0.99);
  border-color: var(--border-accent);
}
.bt-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.bt-id { font-weight: 600; }
.bt-cfg { font-size: 11px; color: var(--text-muted); }
.bt-name {
  margin-top: 6px;
  font-size: 13.5px;
  color: var(--text-primary);
}
.bt-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 10px;
  padding: 8px 0;
  border-top: 1px solid var(--border-soft);
}
.bt-metric { text-align: center; }
.bt-mlabel { font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; }
.bt-mvalue { font-size: 14px; font-weight: 600; margin-top: 2px; }
.bt-foot {
  margin-top: 6px;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
