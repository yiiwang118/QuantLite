<script setup lang="ts">
import { onActivated, onMounted, ref, h } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard, NDataTable, NSpace, NButton, NIcon, NTime, NText, NEmpty,
  NPopconfirm, useMessage
} from 'naive-ui'
import { OpenOutline, TrashOutline, RefreshOutline, FlaskOutline } from '@vicons/ionicons5'
import { api, type StrategyRow, AuthRequired } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const message = useMessage()

const rows = ref<StrategyRow[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const r = await api.get<StrategyRow[]>('/strategies')
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

async function del(id: number, name: string) {
  try {
    await api.delete(`/strategies/${id}`)
    message.success(`已删除 ${name}`)
    await load()
  } catch (e) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else message.error('删除失败')
  }
}

function openInLab(s: StrategyRow) {
  // 跳到 Lab；通过 query 让 Lab 取这个策略 dsl
  router.push({ name: 'lab' })
  // 注意：Lab 当前是从 Strategies 下拉里加载的，简化做法：
  // Lab 已经 onMounted 时拉 list_strategies，所以这条策略会在下拉里
  setTimeout(() => message.info(`在「策略实验室」打开「打开策略」下拉选择 ${s.name}`), 200)
}

const columns = [
  {
    title: 'ID',
    key: 'id',
    width: 60,
    render: (r: StrategyRow) => h('span', { class: 'mono muted', style: 'font-size: 12px' }, '#' + r.id),
  },
  {
    title: '名称',
    key: 'name',
    render: (r: StrategyRow) => h('span', { class: 'mono', style: 'font-weight: 600' }, r.name),
  },
  {
    title: '创建人',
    key: 'created_by',
    width: 120,
    render: (r: StrategyRow) => h('span', { style: 'font-size: 13px' }, r.created_by),
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 150,
    render: (r: StrategyRow) => h(NTime, {
      time: new Date(r.created_at + 'Z'), type: 'relative',
    }),
  },
  {
    title: '更新时间',
    key: 'updated_at',
    width: 150,
    render: (r: StrategyRow) => h(NTime, {
      time: new Date(r.updated_at + 'Z'), type: 'relative',
    }),
  },
  {
    title: 'DSL 长度',
    key: 'dsl_size',
    width: 110,
    render: (r: StrategyRow) => h('span', { class: 'mono muted', style: 'font-size: 12px' },
      r.dsl.length + ' 字符'),
  },
  {
    title: '',
    key: 'action',
    width: 160,
    render: (r: StrategyRow) => h(NSpace, { size: 6 }, () => [
      h(NButton, {
        text: true, type: 'primary', size: 'small',
        onClick: () => openInLab(r),
      }, () => [h(NIcon, null, () => h(FlaskOutline)), ' 在实验室打开']),
      h(NPopconfirm, {
        onPositiveClick: () => del(r.id, r.name),
      }, {
        trigger: () => h(NButton, { text: true, type: 'error', size: 'small' },
          () => [h(NIcon, null, () => h(TrashOutline))]),
        default: () => `确定删除「${r.name}」？历史回测记录会保留但 strategy_id 会变 NULL。`,
      }),
    ]),
  },
]
</script>

<template>
  <NCard>
    <template #header>
      <NSpace align="center" :size="10">
        <span>策略库</span>
        <NText depth="3" class="mono" style="font-size: 12px; font-weight: 400">
          {{ rows.length }} 个已保存策略
        </NText>
      </NSpace>
    </template>
    <template #header-extra>
      <NSpace>
        <NButton @click="router.push({ name: 'lab' })" type="primary">
          <template #icon><NIcon><FlaskOutline /></NIcon></template>
          去实验室
        </NButton>
        <NButton @click="load">
          <template #icon><NIcon><RefreshOutline /></NIcon></template>
          刷新
        </NButton>
      </NSpace>
    </template>
    <!-- 桌面：表格 -->
    <div class="desktop-only">
      <NDataTable :columns="columns" :data="rows" :loading="loading"
        :bordered="false" :pagination="{ pageSize: 30 }" size="small" :striped="true" />
    </div>

    <!-- 移动：卡片列表 -->
    <div class="mobile-only strategy-cards">
      <div v-for="r in rows" :key="r.id" class="strategy-card">
        <div class="sc-head">
          <span class="muted mono" style="font-size: 11px">#{{ r.id }}</span>
          <span class="sc-name mono">{{ r.name }}</span>
        </div>
        <div class="sc-meta">
          <span>{{ r.created_by }}</span>
          <span class="muted">·</span>
          <NTime :time="new Date(r.updated_at + 'Z')" type="relative" />
          <span class="muted">·</span>
          <span class="mono">{{ r.dsl.length }} 字符</span>
        </div>
        <div class="sc-actions">
          <NButton size="small" type="primary" tertiary @click="openInLab(r)">
            <template #icon><NIcon><FlaskOutline /></NIcon></template>
            打开
          </NButton>
          <NPopconfirm @positive-click="del(r.id, r.name)">
            <template #trigger>
              <NButton size="small" type="error" tertiary>
                <template #icon><NIcon><TrashOutline /></NIcon></template>
              </NButton>
            </template>
            确定删除「{{ r.name }}」？
          </NPopconfirm>
        </div>
      </div>
    </div>

    <NEmpty v-if="!loading && rows.length === 0"
      description="还没有保存的策略。去「策略实验室」跑一次回测后点「保存策略」。"
      style="padding: 60px 0">
      <template #extra>
        <NButton type="primary" @click="router.push({ name: 'lab' })">去实验室</NButton>
      </template>
    </NEmpty>
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
  :deep(.n-card-header__extra .n-space) { width: 100%; flex-direction: column; }
  :deep(.n-card-header__extra .n-button) { width: 100%; }
}

.strategy-cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.strategy-card {
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--surface-1);
  border: 1px solid var(--border-soft);
}
.sc-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.sc-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
}
.sc-meta {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.sc-actions {
  margin-top: 10px;
  display: flex;
  gap: 6px;
}
</style>
