<script setup lang="ts">
import { onActivated, onMounted, onUnmounted, ref, h, computed } from 'vue'
import {
  NCard, NSpace, NGrid, NGi, NButton, NIcon, NTag, NDataTable, NText,
  NDivider, NEmpty, NSkeleton, useMessage, NAlert, NTime, NTooltip
} from 'naive-ui'
import {
  CloudDownloadOutline, CalendarOutline,
  CheckmarkCircle, AlertCircle, TimeOutline, FlashOutline
} from '@vicons/ionicons5'
import { api, type FetchResp, type FetchResult, AuthRequired, type OverviewResp,
  type ScheduleResp, type ScheduleJob } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const message = useMessage()

const overview = ref<OverviewResp | null>(null)
const schedule = ref<ScheduleResp | null>(null)
const loading = ref(true)
const log = ref<Array<{ ts: string; kind: string; text: string; results?: FetchResult[] }>>([])
const busy = ref<Record<string, boolean>>({})
let schedulePoll: number | null = null

async function loadOverview() {
  loading.value = true
  try {
    const [ov, sc] = await Promise.all([
      api.get<OverviewResp>('/overview'),
      api.get<ScheduleResp>('/schedule'),
    ])
    overview.value = ov.data
    schedule.value = sc.data
  } catch (e) {
    if (e instanceof AuthRequired) auth.requireLogin()
  } finally {
    loading.value = false
  }
}

async function loadSchedule() {
  try {
    const sc = await api.get<ScheduleResp>('/schedule')
    schedule.value = sc.data
  } catch {}
}

async function triggerScheduledNow(universe: string) {
  busy.value[`s-${universe}`] = true
  try {
    await api.post(`/schedule/trigger/${universe}`)
    message.info(`已排队 ${universe}，约 30 秒后完成`)
    // 5 秒后开始轮询直到 last_run 更新
    setTimeout(loadSchedule, 5000)
    setTimeout(loadSchedule, 15000)
    setTimeout(loadSchedule, 30000)
    setTimeout(() => { loadSchedule(); loadOverview() }, 45000)
  } catch (e) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else message.error('触发失败')
  } finally {
    setTimeout(() => { busy.value[`s-${universe}`] = false }, 30000)
  }
}

onMounted(() => {
  loadOverview()
  schedulePoll = window.setInterval(loadSchedule, 60_000)  // 每分钟刷一次 schedule 状态
})
onActivated(loadOverview)
onUnmounted(() => {
  if (schedulePoll) clearInterval(schedulePoll)
})

function nowIso() {
  return new Date().toISOString().slice(0, 19).replace('T', ' ')
}

async function fetchUniverse(name: string) {
  busy.value[`u-${name}`] = true
  try {
    const r = await api.post<FetchResp>('/data/fetch', { universe: name })
    const s = r.data.summary
    log.value.unshift({
      ts: nowIso(), kind: 'fetch',
      text: `拉取 ${name}：成功 ${s.ok}，错误 ${s.errors}，新增 ${s.rows_added} 行`,
      results: r.data.results
    })
    if (s.errors === 0) message.success(`${name} 已更新`)
    else message.warning(`${name} 部分失败：${s.errors} 个`)
    await loadOverview()
  } catch (e) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else {
      message.error(`${name} 拉取失败`)
      log.value.unshift({ ts: nowIso(), kind: 'error', text: `拉取 ${name} 失败：${(e as Error).message}` })
    }
  } finally {
    busy.value[`u-${name}`] = false
  }
}

async function refreshCalendar(market: string) {
  busy.value[`c-${market}`] = true
  try {
    const r = await api.post(`/calendar/${market}/refresh`)
    log.value.unshift({
      ts: nowIso(), kind: 'calendar',
      text: `刷新 ${market.toUpperCase()} 交易日历：${r.data.added_or_kept} 条`
    })
    message.success(`${market.toUpperCase()} 日历已刷新`)
    await loadOverview()
  } catch (e) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else message.error(`${market} 日历刷新失败`)
  } finally {
    busy.value[`c-${market}`] = false
  }
}

const resultColumns = [
  {
    title: '市场', key: 'market', width: 70,
    render: (r: FetchResult) => h(NTag, {
      type: r.market === 'cn' ? 'error' : 'info', size: 'small', bordered: false
    }, () => r.market.toUpperCase())
  },
  {
    title: 'Symbol', key: 'symbol', width: 100,
    render: (r: FetchResult) => h('code', { class: 'mono' }, r.symbol)
  },
  {
    title: '状态', key: 'status', width: 110,
    render: (r: FetchResult) => {
      const map: Record<string, any> = {
        updated: ['success', '已更新'],
        no_new_rows: ['default', '无新增'],
        up_to_date: ['default', '已最新'],
        empty: ['warning', '空数据'],
        error: ['error', '错误'],
      }
      const [type, label] = map[r.status] || ['default', r.status]
      return h(NTag, { type, size: 'small', bordered: false }, () => label)
    }
  },
  {
    title: '新增', key: 'rows_added', width: 100, align: 'right' as const,
    render: (r: FetchResult) => h('span', { class: 'mono' }, r.rows_added.toLocaleString())
  },
  {
    title: '总行数', key: 'total_rows', width: 100, align: 'right' as const,
    render: (r: FetchResult) => h('span', { class: 'mono muted' }, r.total_rows.toLocaleString())
  },
  {
    title: '最大日期', key: 'max_date',
    render: (r: FetchResult) => h('span', { class: 'mono' }, r.max_date || '-')
  }
]
</script>

<template>
  <div>
    <NAlert title="数据操作面板" type="info" :show-icon="true" closable
      style="margin-bottom: 18px">
      从 akshare 拉取行情数据。每个 universe 是一组预定义股票池。增量拉取自动跳过已缓存日期；
      多 worker 并发安全；东财失败自动降级到新浪。
    </NAlert>

    <!-- 定时拉取状态 -->
    <NCard v-if="schedule?.enabled" class="schedule-card" style="margin-bottom: 18px">
      <template #header>
        <NSpace align="center" :size="10">
          <span class="dot-live" />
          <span>自动拉取</span>
          <NText depth="3" style="font-size: 12px; font-weight: 400">
            {{ schedule.tz }}
          </NText>
        </NSpace>
      </template>
      <NGrid :cols="2" :x-gap="16" :y-gap="12" responsive="screen" item-responsive>
        <NGi v-for="job in schedule.jobs" :key="job.id" span="2 m:1">
          <div class="job-row">
            <div class="job-row-main">
              <NSpace align="center" :size="10">
                <NTag :type="job.universe.startsWith('cn') ? 'error' : 'info'"
                  :bordered="false" size="small">
                  {{ job.universe }}
                </NTag>
                <div class="job-time-block">
                  <div class="muted" style="font-size: 11px; letter-spacing: 0.06em">NEXT RUN</div>
                  <div class="mono" style="font-size: 13px; font-weight: 500">
                    <NTime v-if="job.next_run" :time="new Date(job.next_run)"
                      format="MM-dd HH:mm" />
                    <span v-else>—</span>
                    <NText depth="3" style="font-size: 11px; margin-left: 6px"
                      v-if="job.next_run">
                      (<NTime :time="new Date(job.next_run)" type="relative" />)
                    </NText>
                  </div>
                </div>
              </NSpace>
              <NButton size="small" tertiary
                :loading="busy[`s-${job.universe}`]"
                @click="triggerScheduledNow(job.universe)">
                <template #icon><NIcon><FlashOutline /></NIcon></template>
                立即跑一次
              </NButton>
            </div>
            <div v-if="job.last_run" class="job-last">
              <NTag size="tiny" :bordered="false"
                :type="job.last_run.status === 'success' ? 'success' :
                       job.last_run.status === 'partial' ? 'warning' : 'error'">
                {{ job.last_run.status }}
              </NTag>
              <NText depth="3" class="mono" style="font-size: 11px">
                上次：<NTime :time="new Date(job.last_run.ts)" type="relative" />
                · {{ job.last_run.duration_s }}s
                · 新增 {{ job.last_run.rows_added }} 行
                <span v-if="job.last_run.errors > 0"> · ⚠ {{ job.last_run.errors }} 个错误</span>
              </NText>
            </div>
            <div v-else class="muted" style="font-size: 11px; margin-top: 6px">
              <NIcon style="vertical-align: -2px"><TimeOutline /></NIcon>
              本次进程还没跑过
            </div>
          </div>
        </NGi>
      </NGrid>
    </NCard>

    <!-- 命名 universe 拉取 -->
    <NGrid :cols="2" :x-gap="16" :y-gap="16" responsive="screen" item-responsive>
      <NGi v-for="m in (overview?.markets ?? [])" :key="m.code" span="2 m:1">
        <NCard class="market-ops" hoverable>
          <div class="ops-head">
            <NSpace align="center" :size="10">
              <NTag :type="m.code === 'cn' ? 'error' : 'info'" :bordered="false" size="medium">
                {{ m.label }}
              </NTag>
              <NText style="font-weight: 600; font-size: 15px">
                {{ m.named_universes.join(', ') || '无 universe' }}
              </NText>
            </NSpace>
            <NText depth="3" class="mono" style="font-size: 12px">
              {{ m.symbols_count }} symbols · {{ m.cache.files }} 文件 · {{ m.cache.size_mb }} MB
            </NText>
          </div>

          <NDivider style="margin: 14px 0" />

          <NSpace>
            <NButton v-for="u in m.named_universes" :key="u"
              type="primary" :loading="busy[`u-${u}`]" @click="fetchUniverse(u)">
              <template #icon><NIcon><CloudDownloadOutline /></NIcon></template>
              拉取 <span class="mono" style="margin-left: 4px">{{ u }}</span>
            </NButton>
            <NButton :loading="busy[`c-${m.code}`]" @click="refreshCalendar(m.code)">
              <template #icon><NIcon><CalendarOutline /></NIcon></template>
              刷新交易日历
            </NButton>
          </NSpace>
        </NCard>
      </NGi>
    </NGrid>

    <!-- 操作日志 -->
    <NCard title="操作日志" style="margin-top: 20px">
      <template #header-extra>
        <NButton size="small" @click="log = []" :disabled="log.length === 0">清空</NButton>
      </template>
      <NEmpty v-if="log.length === 0" description="还没有操作记录" style="padding: 30px 0" />
      <NSpace vertical :size="12">
        <div v-for="(item, idx) in log" :key="idx" class="log-item">
          <NSpace align="center" :wrap="false">
            <NIcon size="16" :color="item.kind === 'error' ? '#ef4444' : '#10b981'">
              <AlertCircle v-if="item.kind === 'error'" />
              <CheckmarkCircle v-else />
            </NIcon>
            <NText depth="3" class="mono" style="font-size: 12px">{{ item.ts }}</NText>
            <NText>{{ item.text }}</NText>
          </NSpace>
          <NDataTable v-if="item.results && item.results.length > 0"
            :columns="resultColumns" :data="item.results"
            :bordered="false" size="small" style="margin-top: 12px"
            :pagination="false" :max-height="280" />
        </div>
      </NSpace>
    </NCard>
  </div>
</template>

<style scoped>
.market-ops {
  transition: transform 0.18s ease;
}
.market-ops:hover {
  transform: translateY(-2px);
}

.schedule-card {
  border: 1px solid rgba(16, 185, 129, 0.18) !important;
  background: linear-gradient(135deg, rgba(16,185,129,0.04), rgba(124,58,237,0.02)) !important;
}
.job-row {
  padding: 12px 14px;
  border-radius: 8px;
  background: var(--surface-1);
  border: 1px solid var(--border-soft);
}
.job-row-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.job-time-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.job-last {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.ops-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}
.log-item {
  padding: 14px 16px;
  border-radius: 8px;
  background: var(--surface-1);
  border: 1px solid var(--border-soft);
}
</style>
