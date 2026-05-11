<script setup lang="ts">
import { onActivated, onMounted, onUnmounted, ref, h, computed, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  NCard, NSpace, NButton, NIcon, NInput, NGrid, NGi, NText, NTag,
  NModal, NForm, NFormItem, NEmpty, NDivider, NDropdown,
  NCollapse, NCollapseItem, NRadio, NRadioGroup, NTooltip,
  useMessage, useDialog
} from 'naive-ui'
import {
  PlayOutline, SaveOutline, CheckmarkCircleOutline, CloseCircleOutline,
  DocumentTextOutline, FolderOpenOutline, ChevronDownOutline, SparklesOutline,
  SettingsOutline, RefreshOutline, FlashOutline, SendOutline, StopOutline,
  CodeSlashOutline, PersonOutline, BulbOutline,
  ChatbubblesOutline, TrashOutline,
} from '@vicons/ionicons5'
import {
  api, type BacktestResp, type ValidateResp, type StrategyRow,
  type ChatResp, type AIStatus, type ChatEvent, streamChat,
  AuthRequired
} from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import MetricCard from '@/components/MetricCard.vue'
import NavCurveChart from '@/components/NavCurveChart.vue'
import Markdown from '@/components/Markdown.vue'

const { t, tm } = useI18n()

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const message = useMessage()
const dialog = useDialog()

const SAMPLE_DSL = `factor mom20 = close / delay(close, 20) - 1
factor vol60 = std(returns(close), 60)
factor score = rank(mom20) - rank(vol60)

strategy {
    universe:  cn:sample
    signal:    score
    select:    top 3
    rebalance: weekly
    start:     2024-01-01
}
`

// ─── State ─────────────────────────────────────────────────

const dsl = ref<string>(SAMPLE_DSL)
const running = ref(false)
const validation = ref<ValidateResp | null>(null)
const result = ref<BacktestResp | null>(null)
const strategies = ref<StrategyRow[]>([])

// Chat state
interface ToolCallView {
  id: string
  name: string
  input: any
  result: any | null
  status: 'running' | 'done' | 'error'
  startedAt: number
  endedAt?: number
}
interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  toolCalls: ToolCallView[]
  thinking: string         // 当前轮次的"思考文字"（LLM 在工具调用之间的解释）
  status: 'streaming' | 'done' | 'error'
  error?: string
  duration_ms?: number
  modelLabel?: string
  startedAt?: number       // assistant 消息开始时间
  thinkingStartedAt?: number  // 当前 thinking 段开始时间
}

// 每秒更新的"现在"时间，用来计算 running 工具的已用时长
const now = ref(Date.now())
let nowTimer: number | null = null
onMounted(() => {
  nowTimer = window.setInterval(() => { now.value = Date.now() }, 500)
})
onUnmounted(() => {
  if (nowTimer) clearInterval(nowTimer)
})

const messages = ref<ChatMessage[]>([])
const input = ref('')
const streaming = ref(false)
const abortController = ref<AbortController | null>(null)
const threadRef = ref<HTMLElement | null>(null)
const expandedTools = ref<Record<string, boolean>>({})

// ─── 会话历史 ───────────────────────────────────────────────
interface ChatSessionMeta {
  id: string
  title: string
  created_at: string
  updated_at: string
}
const currentSessionId = ref<string>('')
const sessions = ref<ChatSessionMeta[]>([])

async function loadSessions() {
  try {
    const r = await api.get<{ sessions: ChatSessionMeta[] }>('/ai/sessions')
    sessions.value = r.data.sessions
  } catch {}
}

async function persistSession() {
  if (messages.value.length === 0) return
  const payload = { messages: messages.value }
  try {
    if (currentSessionId.value) {
      await api.put(`/ai/sessions/${currentSessionId.value}`, payload)
    } else {
      const r = await api.post<{ id: string; title: string }>('/ai/sessions', payload)
      currentSessionId.value = r.data.id
    }
    loadSessions()
  } catch (e) {
    console.warn('persist session failed', e)
  }
}

async function loadSession(id: string) {
  if (streaming.value) {
    message.warning('请先停止当前对话')
    return
  }
  try {
    const r = await api.get<{ id: string; messages: ChatMessage[] }>(`/ai/sessions/${id}`)
    messages.value = r.data.messages || []
    currentSessionId.value = id
    scrollToBottom()
  } catch {}
}

function confirmDeleteSession(s: ChatSessionMeta) {
  dialog.warning({
    title: '删除会话',
    content: `确定删除「${s.title}」吗？此操作不可撤销`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.delete(`/ai/sessions/${s.id}`)
        if (currentSessionId.value === s.id) {
          messages.value = []
          currentSessionId.value = ''
        }
        loadSessions()
      } catch {}
    },
  })
}

function formatSessionTime(s: string) {
  // 后端用 datetime('now') 写的字符串是 'YYYY-MM-DD HH:MM:SS'（UTC），手动加 Z
  const iso = s.includes('T') ? s : s.replace(' ', 'T') + 'Z'
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 7 * 86400) return `${Math.floor(diff / 86400)} 天前`
  return d.toLocaleDateString()
}

// 模型选择
const aiStatus = ref<AIStatus | null>(null)
const selectedModelId = ref<string>('')

async function loadAIStatus() {
  try {
    const r = await api.get<AIStatus>('/ai/status')
    aiStatus.value = r.data
    if (r.data.enabled && !selectedModelId.value) {
      const def = r.data.models.find(m => m.id === r.data.default_model_id && m.configured)
      const first = r.data.models.find(m => m.configured)
      selectedModelId.value = def?.id || first?.id || ''
    }
  } catch {}
}

const configuredModels = computed(() =>
  aiStatus.value?.models.filter(m => m.configured) || []
)

// ─── DSL validation ─────────────────────────────────────────

let validateTimer: number | null = null
function scheduleValidate() {
  if (validateTimer) clearTimeout(validateTimer)
  validateTimer = window.setTimeout(validate, 500)
}

async function validate() {
  try {
    const r = await api.post<ValidateResp>('/dsl/validate', { dsl: dsl.value })
    validation.value = r.data
  } catch (e) {
    if (e instanceof AuthRequired) auth.requireLogin()
  }
}

// ─── 跑回测（DSL 编辑器手动按）─────────────────────────────

async function runBacktest() {
  running.value = true
  result.value = null
  try {
    const r = await api.post<BacktestResp>('/backtest',
      { dsl: dsl.value }, { timeout: 180_000 })
    result.value = r.data
    message.success(`回测完成 (${r.data.duration_ms}ms)`)
  } catch (e: any) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else {
      const detail = e.response?.data?.detail || e.message || '未知错误'
      dialog.error({ title: '回测失败', content: detail })
    }
  } finally {
    running.value = false
  }
}

// ─── Chat / Agent ──────────────────────────────────────────

// 滚动锁定：用户向上滑离底部后停止 auto-scroll；回到底部附近自动恢复
const stickToBottom = ref(true)
function onThreadScroll() {
  const el = threadRef.value
  if (!el) return
  // 距离底部 < 60px 视为"贴底"
  stickToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 60
}
function jumpToBottom() {
  const el = threadRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
  stickToBottom.value = true
}
function scrollToBottom(force = false) {
  if (!force && !stickToBottom.value) return
  nextTick(() => {
    if (threadRef.value) {
      threadRef.value.scrollTop = threadRef.value.scrollHeight
    }
  })
}

async function send() {
  const text = input.value.trim()
  if (!text) return

  if (!selectedModelId.value) {
    if (!aiStatus.value?.enabled) {
      dialog.warning({
        title: 'AI 未配置',
        content: '需要先在「设置」配置至少一个模型',
        positiveText: '去设置',
        onPositiveClick: () => router.push({ name: 'settings' }),
      })
    } else {
      message.warning('请先在右侧选择一个模型')
    }
    return
  }

  // 1. 用户消息
  const userMsg: ChatMessage = {
    id: `user-${Date.now()}`,
    role: 'user', text, toolCalls: [], thinking: '', status: 'done',
  }
  messages.value.push(userMsg)
  input.value = ''
  // 用户发消息时主动跳底（即使之前他向上看过历史）
  stickToBottom.value = true
  scrollToBottom(true)

  // 2. assistant 占位
  const asstMsg: ChatMessage = {
    id: `asst-${Date.now()}`,
    role: 'assistant', text: '', toolCalls: [], thinking: '', status: 'streaming',
    startedAt: Date.now(),
    thinkingStartedAt: Date.now(),
  }
  messages.value.push(asstMsg)
  scrollToBottom()

  streaming.value = true
  abortController.value = new AbortController()
  const t0 = Date.now()

  try {
    await streamChat(
      { text, model_id: selectedModelId.value },
      (event) => {
        if (event.type === 'started') {
          asstMsg.modelLabel = event.model.label
        } else if (event.type === 'thinking') {
          // 新的迭代：清空 thinking 文字（上一轮的），重置思考时间
          asstMsg.thinking = ''
          asstMsg.thinkingStartedAt = Date.now()
        } else if (event.type === 'thinking_text') {
          asstMsg.thinking = event.text
        } else if (event.type === 'tool_call_start') {
          asstMsg.toolCalls.push({
            id: event.id, name: event.name, input: event.input,
            result: null, status: 'running',
            startedAt: Date.now(),
          })
          asstMsg.thinkingStartedAt = undefined  // 进入工具阶段，停 thinking 计时
        } else if (event.type === 'tool_call_end') {
          const tc = asstMsg.toolCalls.find(t => t.id === event.id)
          if (tc) {
            tc.result = event.result
            tc.status = event.result?.ok === false ? 'error' : 'done'
            tc.endedAt = Date.now()
          }
          asstMsg.thinkingStartedAt = Date.now()  // 工具结束，重启 thinking 计时（等下一个 thinking 事件）
        } else if (event.type === 'final_message') {
          asstMsg.text = event.text
          asstMsg.thinking = ''  // 最终消息出现后，清掉中间 thinking
        } else if (event.type === 'done') {
          asstMsg.status = 'done'
          asstMsg.duration_ms = Date.now() - t0
          // 应用 DSL + 回测结果
          if (event.result.dsl) {
            dsl.value = event.result.dsl
            validate()
          }
          if (event.result.backtest_result) {
            const br = event.result.backtest_result
            result.value = {
              id: null, strategy_id: null, saved: false,
              metrics: br.metrics, nav_curve: br.nav_curve,
              benchmark_curve: br.benchmark_curve, benchmark_metrics: br.benchmark_metrics,
              excess_return: br.excess_return,
              rebalance_dates: br.rebalance_dates || [],
              holdings_history: br.holdings_history || {},
              params: br.params, duration_ms: br.duration_ms, rows_used: br.rows_used,
              triggered_by: auth.username || '',
            }
          }
        } else if (event.type === 'error') {
          asstMsg.status = 'error'
          asstMsg.error = event.error
        }
        scrollToBottom()
      },
      abortController.value.signal,
    )
    if (asstMsg.status === 'streaming') {
      asstMsg.status = 'done'
      asstMsg.duration_ms = Date.now() - t0
    }
  } catch (e: any) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else if (e.name === 'AbortError') {
      asstMsg.status = 'error'
      asstMsg.error = '已中止'
    } else {
      asstMsg.status = 'error'
      asstMsg.error = e.message || String(e)
    }
  } finally {
    streaming.value = false
    abortController.value = null
    scrollToBottom()
    persistSession()
  }
}

function stopStream() {
  if (abortController.value) {
    abortController.value.abort()
  }
}

function newChat() {
  if (streaming.value) {
    message.warning('请先停止当前对话')
    return
  }
  messages.value = []
  currentSessionId.value = ''
  result.value = null
}

function describeTool(tc: ToolCallView): string {
  if (tc.status === 'running') {
    const elapsed = Math.floor((now.value - tc.startedAt) / 1000)
    return elapsed > 0 ? `${t('lab.elapsed')} ${elapsed}s` : t('lab.thinking')
  }
  if (!tc.result) return ''
  if (tc.result.ok === false) return tc.result.error || t('common.failed')
  const elapsed = tc.endedAt
    ? ((tc.endedAt - tc.startedAt) / 1000).toFixed(1)
    : null
  const suffix = elapsed ? ` · ${elapsed}s` : ''
  if (tc.name === 'validate_dsl') {
    return `✓ factors: ${(tc.result.factors || []).join(', ')}${suffix}`
  }
  if (tc.name === 'run_backtest' && tc.result.strategy) {
    const s = tc.result.strategy
    return `累计 ${(s.cum_return * 100).toFixed(2)}% · 夏普 ${s.sharpe.toFixed(2)} · 超额 ${(tc.result.excess_return * 100).toFixed(2)}pp${suffix}`
  }
  if (tc.name === 'list_universes') return `${(tc.result.universes || []).length} 个 universe${suffix}`
  if (tc.name === 'list_saved_strategies') return `${(tc.result.strategies || []).length} 个策略${suffix}`
  return `完成${suffix}`
}

function toolStatusIcon(status: string): string {
  if (status === 'running') return '◐'
  if (status === 'done') return '✓'
  if (status === 'error') return '✗'
  return '·'
}

// 当前 thinking 已用时间（秒）
function thinkingElapsed(msg: ChatMessage): number {
  if (!msg.thinkingStartedAt) return 0
  return Math.floor((now.value - msg.thinkingStartedAt) / 1000)
}

const suggestedPrompts = computed(() => tm('lab.suggestedPrompts') as string[])

function usePrompt(p: string) {
  input.value = p
}

// ─── 保存策略 ──────────────────────────────────────────────

const saveDialogOpen = ref(false)
const saveName = ref('')

function openSaveDialog() {
  if (!result.value) {
    message.warning('请先有一份回测结果')
    return
  }
  saveName.value = ''
  saveDialogOpen.value = true
}

async function submitSave() {
  if (!saveName.value.trim()) return
  try {
    const r = await api.post<BacktestResp>('/backtest',
      { dsl: dsl.value, save_as: saveName.value.trim() }, { timeout: 120_000 })
    result.value = r.data
    saveDialogOpen.value = false
    message.success(`已保存「${saveName.value}」`)
    await loadStrategies()
  } catch (e: any) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else message.error(`保存失败：${e.response?.data?.detail || e.message}`)
  }
}

async function loadStrategies() {
  try {
    const r = await api.get<StrategyRow[]>('/strategies')
    strategies.value = r.data
  } catch {}
}

function loadStrategy(s: StrategyRow) {
  dsl.value = s.dsl
  result.value = null
  validate()
  message.info(`已加载策略：${s.name}`)
}

// ─── 初始化 ─────────────────────────────────────────────────

onMounted(async () => {
  const bid = route.query.backtest_id
  if (bid) {
    try {
      const r = await api.get<any>(`/backtests/${bid}`)
      dsl.value = r.data.dsl
      result.value = {
        id: r.data.id, strategy_id: r.data.strategy_id, saved: true,
        metrics: r.data.metrics, nav_curve: r.data.nav_curve,
        benchmark_curve: r.data.benchmark_curve || [],
        benchmark_metrics: r.data.benchmark_metrics || r.data.metrics,
        excess_return: r.data.excess_return || 0,
        rebalance_dates: [], holdings_history: {},
        params: r.data.params, duration_ms: r.data.duration_ms,
        rows_used: 0, triggered_by: r.data.created_by,
      }
    } catch (e) {
      if (e instanceof AuthRequired) auth.requireLogin()
    }
  }
  await Promise.all([loadStrategies(), validate(), loadAIStatus(), loadSessions()])
})

// KeepAlive 下每次切回 Lab 重新拉一遍（用户可能刚改过 Settings 里的 label）
onActivated(() => {
  loadAIStatus()
  loadStrategies()
  loadSessions()
})

</script>

<template>
  <div class="ai-page">
    <!-- ─── 左中：聊天 + DSL + 结果 ─── -->
    <div class="ai-main">
      <!-- 顶 -->
      <div class="ai-header">
        <div>
          <div class="muted" style="font-size: 11px; letter-spacing: 0.18em">{{ t('lab.subtitle') }}</div>
          <h1>{{ t('lab.title') }}</h1>
        </div>
        <NSpace>
          <NButton v-if="messages.length > 0" size="small" tertiary @click="newChat">
            <template #icon><NIcon><RefreshOutline /></NIcon></template>
            {{ t('lab.newChat') }}
          </NButton>
        </NSpace>
      </div>

      <!-- 聊天线程 -->
      <div class="chat-area">
        <div ref="threadRef" class="chat-thread" @scroll.passive="onThreadScroll">
        <!-- 空态 -->
        <div v-if="messages.length === 0" class="chat-empty">
          <div class="empty-icon">
            <NIcon size="48" color="var(--accent)"><SparklesOutline /></NIcon>
          </div>
          <h2 class="gradient-text">{{ t('lab.heroTitle') }}</h2>
          <p class="muted">{{ t('lab.heroDesc') }}</p>
          <div class="suggested-prompts">
            <div v-for="p in suggestedPrompts" :key="p" class="prompt-chip" @click="usePrompt(p)">
              {{ p }}
            </div>
          </div>
        </div>

        <!-- 消息 -->
        <template v-else>
          <div v-for="msg in messages" :key="msg.id" class="msg" :class="`role-${msg.role}`">
            <!-- 用户消息：右气泡 -->
            <div v-if="msg.role === 'user'" class="user-bubble">
              <div class="role-tag">
                <NIcon size="14"><PersonOutline /></NIcon>
                <span>{{ auth.username }}</span>
              </div>
              <div class="bubble-text">{{ msg.text }}</div>
            </div>

            <!-- assistant 消息：完整块 -->
            <div v-else class="assistant-block">
              <div class="role-tag">
                <NIcon size="14" color="var(--accent)"><SparklesOutline /></NIcon>
                <span>{{ msg.modelLabel || 'AI' }}</span>
                <span v-if="msg.duration_ms" class="muted mono" style="font-size: 11px">
                  · {{ (msg.duration_ms / 1000).toFixed(1) }}s
                </span>
              </div>

              <!-- 工具调用链 -->
              <div v-if="msg.toolCalls.length > 0" class="tool-chain">
                <div v-for="tc in msg.toolCalls" :key="tc.id"
                  class="tool-step" :class="`status-${tc.status}`">
                  <div class="tool-step-head"
                    @click="expandedTools[tc.id] = !expandedTools[tc.id]">
                    <span class="tool-icon" :class="`status-${tc.status}`">
                      {{ toolStatusIcon(tc.status) }}
                    </span>
                    <code class="tool-name">{{ tc.name }}</code>
                    <span class="tool-summary">{{ describeTool(tc) }}</span>
                    <NIcon size="12" class="tool-expand-icon">
                      <ChevronDownOutline />
                    </NIcon>
                  </div>
                  <div v-if="expandedTools[tc.id]" class="tool-detail">
                    <div class="detail-row">
                      <div class="detail-label">INPUT</div>
                      <pre class="mono">{{ JSON.stringify(tc.input, null, 2) }}</pre>
                    </div>
                    <div v-if="tc.result" class="detail-row">
                      <div class="detail-label">RESULT</div>
                      <pre class="mono">{{ JSON.stringify(tc.result, null, 2) }}</pre>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 思考中：thinking 文字为空时显示动画占位；有内容时用 Markdown 完整渲染 -->
              <template v-if="msg.status === 'streaming' && !msg.text
                && !msg.toolCalls.some(tc => tc.status === 'running')">
                <div v-if="!msg.thinking" class="thinking-bubble">
                  <span class="thinking-dot" />
                  <span class="thinking-dot" />
                  <span class="thinking-dot" />
                  <span style="margin-left: 8px">
                    {{ t('lab.thinking') }}
                    <span v-if="thinkingElapsed(msg) > 0" class="muted mono"
                      style="font-size: 11px; margin-left: 6px">
                      · {{ thinkingElapsed(msg) }}s
                    </span>
                  </span>
                </div>
                <div v-else class="inline-thinking">
                  <Markdown :text="msg.thinking" />
                  <div v-if="thinkingElapsed(msg) > 0" class="muted mono"
                    style="font-size: 11px; margin-top: 6px">
                    {{ thinkingElapsed(msg) }}s
                  </div>
                </div>
              </template>

              <!-- 最终文本（用 Markdown 渲染）-->
              <div v-if="msg.text" class="assistant-text">
                <Markdown :text="msg.text" />
              </div>

              <!-- 错误 -->
              <div v-if="msg.status === 'error'" class="error-bubble">
                <NIcon size="14"><CloseCircleOutline /></NIcon>
                <span>{{ msg.error || '失败' }}</span>
              </div>
            </div>
          </div>
        </template>
        </div>
        <!-- 跳到最新（只在 streaming + 离开底部时显示）-->
        <transition name="fade">
          <button v-if="!stickToBottom && streaming" class="jump-to-bottom"
            @click="jumpToBottom" :title="t('lab.jumpToBottom')">
            <NIcon size="16"><ChevronDownOutline /></NIcon>
          </button>
        </transition>
      </div>

      <!-- 输入区 -->
      <div class="chat-input">
        <NInput v-model:value="input" type="textarea"
          :autosize="{ minRows: 1, maxRows: 6 }"
          :placeholder="streaming
            ? t('lab.inputDisabledWhileStreaming')
            : t('lab.inputPlaceholder')"
          :disabled="streaming"
          @keydown.ctrl.enter="send" @keydown.meta.enter="send" />
        <div class="input-actions">
          <NText depth="3" style="font-size: 11px">
            {{ t('lab.modelLabel') }}：<span class="mono">{{
              configuredModels.find(m => m.id === selectedModelId)?.label || '—'
            }}</span>
          </NText>
          <NSpace>
            <NButton v-if="streaming" tertiary type="error" @click="stopStream">
              <template #icon><NIcon><StopOutline /></NIcon></template>
              {{ t('common.stop') }}
            </NButton>
            <NButton v-else type="primary" @click="send"
              :disabled="!input.trim() || !selectedModelId">
              <template #icon><NIcon><SendOutline /></NIcon></template>
              {{ t('common.send') }}
            </NButton>
          </NSpace>
        </div>
      </div>

      <!-- DSL 编辑器（默认折叠）-->
      <NCollapse :default-expanded-names="result ? [] : (validation?.factors ? [] : [])"
        accordion arrow-placement="right">
        <NCollapseItem name="dsl">
          <template #header>
            <NSpace align="center" :size="10">
              <NIcon size="14" color="var(--accent)"><CodeSlashOutline /></NIcon>
              <span style="font-weight: 600">DSL 编辑器</span>
              <NTag v-if="validation?.ok" size="tiny" :bordered="false" type="success">语法 OK</NTag>
              <NTag v-else-if="validation && !validation.ok" size="tiny" :bordered="false" type="error">
                L{{ validation.line }}:{{ validation.col }}
              </NTag>
              <NText v-if="validation?.ok && validation.strategy" depth="3" class="mono" style="font-size: 11px">
                {{ validation.strategy.universe }} · top {{ validation.strategy.top_n }} · {{ validation.strategy.rebalance }}
              </NText>
            </NSpace>
          </template>
          <NInput v-model:value="dsl" type="textarea"
            class="dsl-editor"
            :autosize="{ minRows: 8, maxRows: 24 }"
            :input-props="{ spellcheck: false, autocomplete: 'off' }"
            @input="scheduleValidate" />
          <div v-if="validation && !validation.ok" class="validation-error mono">
            {{ validation.error }}
          </div>
          <NSpace style="margin-top: 10px">
            <NButton type="primary" :loading="running" @click="runBacktest" size="small">
              <template #icon><NIcon><PlayOutline /></NIcon></template>
              运行回测
            </NButton>
            <NButton v-if="result" size="small" secondary type="success" @click="openSaveDialog">
              <template #icon><NIcon><SaveOutline /></NIcon></template>
              保存策略
            </NButton>
          </NSpace>
        </NCollapseItem>
      </NCollapse>

      <!-- 回测结果（出现在 agent 跑完或手动跑完后）-->
      <div v-if="result" class="result-section">
        <!-- 策略类型 + 成本 摘要条 -->
        <NCard size="small" :bordered="false" style="background: var(--surface-1); margin-bottom: 4px">
          <NSpace align="center" :size="14" justify="space-between">
            <NSpace align="center" :size="14">
              <NTag size="small" :bordered="false" :type="(result.params.bottom_n || 0) > 0 ? 'info' : 'default'">
                {{ (result.params.bottom_n || 0) > 0
                   ? `多空 top ${result.params.top_n} / bottom ${result.params.bottom_n}`
                   : `仅多头 top ${result.params.top_n}` }}
              </NTag>
              <span class="muted mono" style="font-size: 12px">
                {{ result.params.universe }} · {{ result.params.rebalance }} ·
                {{ result.nav_curve.length }} 日
              </span>
              <span v-if="(result.params.cost || 0) > 0" class="muted mono" style="font-size: 12px">
                · 成本 {{ ((result.params.cost || 0) * 10000).toFixed(1) }} bps/单边
              </span>
            </NSpace>
            <span v-if="(result.total_cost || 0) > 0" class="muted mono" style="font-size: 12px">
              累计成本拖累 −{{ ((result.total_cost || 0) * 100).toFixed(2) }}%
            </span>
          </NSpace>
        </NCard>

        <NGrid :cols="6" :x-gap="10" :y-gap="10" responsive="screen" item-responsive>
          <NGi span="6 s:3 m:2">
            <MetricCard label="累计收益" :value="result.metrics.cum_return"
              format="pct" color="up_good"
              :hint="`基准 ${(result.benchmark_metrics.cum_return * 100).toFixed(2)}%`" />
          </NGi>
          <NGi span="6 s:3 m:2">
            <MetricCard label="年化收益" :value="result.metrics.annual_return"
              format="pct" color="up_good"
              :hint="`基准 ${(result.benchmark_metrics.annual_return * 100).toFixed(2)}%`" />
          </NGi>
          <NGi span="6 s:3 m:2">
            <MetricCard label="夏普" :value="result.metrics.sharpe"
              format="ratio" color="up_good"
              :hint="`基准 ${result.benchmark_metrics.sharpe.toFixed(2)}`" />
          </NGi>
          <NGi span="6 s:3 m:2">
            <MetricCard label="年化波动" :value="result.metrics.annual_vol"
              format="pct" color="neutral"
              :hint="`基准 ${(result.benchmark_metrics.annual_vol * 100).toFixed(2)}%`" />
          </NGi>
          <NGi span="6 s:3 m:2">
            <MetricCard label="最大回撤" :value="result.metrics.max_drawdown"
              format="pct" color="up_bad"
              :hint="`基准 ${(result.benchmark_metrics.max_drawdown * 100).toFixed(2)}%`" />
          </NGi>
          <NGi span="6 s:3 m:2">
            <MetricCard label="胜率" :value="result.metrics.win_rate"
              format="pct" color="neutral"
              :hint="`基准 ${(result.benchmark_metrics.win_rate * 100).toFixed(2)}%`" />
          </NGi>
        </NGrid>

        <NCard class="excess-card" style="margin-top: 10px">
          <div class="excess-row">
            <div>
              <div class="muted" style="font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase">
                超额收益
              </div>
              <div class="excess-value mono"
                :class="result.excess_return >= 0 ? 'good' : 'bad'">
                {{ result.excess_return >= 0 ? '+' : '' }}{{ (result.excess_return * 100).toFixed(2) }}<span class="unit">pp</span>
              </div>
              <div class="muted" style="font-size: 11px">
                策略 {{ (result.metrics.cum_return * 100).toFixed(2) }}%
                vs 基准 {{ (result.benchmark_metrics.cum_return * 100).toFixed(2) }}%
              </div>
            </div>
            <span v-if="result.excess_return >= 0" class="tag-good">✓ 跑赢基准</span>
            <span v-else class="tag-bad">✗ 跑输基准</span>
          </div>
        </NCard>

        <NCard style="margin-top: 10px">
          <template #header>
            <NSpace align="center" :size="10">
              <span>净值曲线</span>
              <NText depth="3" class="mono" style="font-size: 11px; font-weight: 400">
                {{ result.params.universe }} · top {{ result.params.top_n }} ·
                {{ result.params.rebalance }} · {{ result.nav_curve.length }} 日
              </NText>
            </NSpace>
          </template>
          <NavCurveChart :nav-curve="result.nav_curve"
            :benchmark-curve="result.benchmark_curve" />
        </NCard>
      </div>
    </div>

    <!-- ─── 右：模型选择 + 工具说明 ─── -->
    <aside class="ai-aside">
      <NCard size="small">
        <template #header>
          <NSpace align="center" :size="8">
            <span style="font-size: 13px; font-weight: 600">模型</span>
            <NTag v-if="aiStatus?.enabled" size="tiny" :bordered="false" type="success">
              {{ configuredModels.length }} 已配
            </NTag>
          </NSpace>
        </template>

        <div v-if="!aiStatus?.enabled" class="aside-empty">
          <NText depth="3" style="font-size: 12px">还没有配置模型</NText>
          <NButton size="small" type="primary" block
            @click="router.push({ name: 'settings' })" style="margin-top: 8px">
            <template #icon><NIcon><SettingsOutline /></NIcon></template>
            去设置
          </NButton>
        </div>

        <div v-else>
          <div v-for="m in configuredModels" :key="m.id"
            class="model-card" :class="{ selected: selectedModelId === m.id }"
            @click="selectedModelId = m.id">
            <div class="model-card-head">
              <div class="model-radio">
                <span v-if="selectedModelId === m.id" class="radio-on" />
                <span v-else class="radio-off" />
              </div>
              <div class="model-card-name">{{ m.label }}</div>
            </div>
            <div class="model-card-meta">
              <NTag size="tiny" :bordered="false"
                :type="m.format === 'anthropic' ? 'info' : 'default'">
                {{ m.format }}
              </NTag>
              <span class="mono muted" style="font-size: 11px">{{ m.model_id }}</span>
            </div>
          </div>

          <NDivider style="margin: 10px 0" />
          <NButton size="tiny" tertiary block
            @click="router.push({ name: 'settings' })">
            <template #icon><NIcon><SettingsOutline /></NIcon></template>
            管理模型
          </NButton>
        </div>
      </NCard>

      <NCard size="small" style="margin-top: 12px">
        <template #header>
          <NSpace align="center" :size="8" justify="space-between" style="width: 100%">
            <NSpace align="center" :size="8">
              <NIcon size="14"><ChatbubblesOutline /></NIcon>
              <span style="font-size: 13px; font-weight: 600">会话历史</span>
              <NTag v-if="sessions.length > 0" size="tiny" :bordered="false">
                {{ sessions.length }}
              </NTag>
            </NSpace>
            <NButton size="tiny" tertiary @click="newChat" :disabled="streaming">
              <template #icon><NIcon><RefreshOutline /></NIcon></template>
              新会话
            </NButton>
          </NSpace>
        </template>

        <div v-if="sessions.length === 0" class="aside-empty">
          <NText depth="3" style="font-size: 12px">暂无历史会话</NText>
        </div>
        <div v-else style="max-height: 320px; overflow-y: auto; margin: 0 -4px;">
          <div v-for="s in sessions" :key="s.id"
            class="session-item" :class="{ 'session-active': currentSessionId === s.id }"
            @click="loadSession(s.id)">
            <div class="session-title">{{ s.title }}</div>
            <div class="session-meta mono muted">{{ formatSessionTime(s.updated_at) }}</div>
            <button class="session-del" :title="`删除「${s.title}」`"
              @click.stop="confirmDeleteSession(s)">
              <NIcon size="12"><TrashOutline /></NIcon>
            </button>
          </div>
        </div>
      </NCard>

      <NCard size="small" style="margin-top: 12px">
        <template #header>
          <NSpace align="center" :size="8">
            <NIcon size="14" color="#fbbf24"><BulbOutline /></NIcon>
            <span style="font-size: 13px; font-weight: 600">Agent 工具</span>
          </NSpace>
        </template>
        <div class="tool-info">
          <code>validate_dsl</code>
          <NText depth="3" style="font-size: 11px">校验 DSL 语法</NText>
        </div>
        <div class="tool-info">
          <code>run_backtest</code>
          <NText depth="3" style="font-size: 11px">真跑回测，给指标 + 基准对照</NText>
        </div>
        <div class="tool-info">
          <code>list_universes</code>
          <NText depth="3" style="font-size: 11px">列可用股票池</NText>
        </div>
        <div class="tool-info">
          <code>list_saved_strategies</code>
          <NText depth="3" style="font-size: 11px">列已保存策略</NText>
        </div>
      </NCard>

      <NCard v-if="strategies.length > 0" size="small" style="margin-top: 12px">
        <template #header>
          <NSpace align="center" :size="8">
            <NIcon size="14"><FolderOpenOutline /></NIcon>
            <span style="font-size: 13px; font-weight: 600">最近策略</span>
          </NSpace>
        </template>
        <div v-for="s in strategies.slice(0, 5)" :key="s.id"
          class="strategy-item" @click="loadStrategy(s)">
          <div class="mono" style="font-size: 12px; font-weight: 500">{{ s.name }}</div>
          <div class="muted" style="font-size: 11px">{{ s.created_by }}</div>
        </div>
      </NCard>
    </aside>

    <!-- 保存策略对话框 -->
    <NModal v-model:show="saveDialogOpen" preset="card" style="width: 420px" title="保存策略">
      <NForm @submit.prevent="submitSave">
        <NFormItem label="名称">
          <NInput v-model:value="saveName" placeholder="如 mom20_top3_weekly"
            @keydown.enter="submitSave" autofocus />
        </NFormItem>
        <NSpace justify="end">
          <NButton @click="saveDialogOpen = false">取消</NButton>
          <NButton type="primary" @click="submitSave" :disabled="!saveName.trim()">保存</NButton>
        </NSpace>
      </NForm>
    </NModal>
  </div>
</template>

<style scoped>
.ai-page {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 16px;
  align-items: start;
  max-width: 1500px;
  margin: 0 auto;
}
@media (max-width: 1100px) {
  .ai-page { grid-template-columns: 1fr; gap: 12px; }
  .ai-aside { order: -1; }
}
@media (max-width: 768px) {
  .ai-page { gap: 10px; }
  .ai-header h1 { font-size: 22px !important; }
  .chat-thread { max-height: 55vh; gap: 12px; }
  .user-bubble { max-width: 92% !important; }
  .chat-empty { padding: 36px 16px; }
  .chat-empty h2 { font-size: 18px; }
  .empty-icon { width: 56px; height: 56px; }
  .suggested-prompts { gap: 6px; }
  .prompt-chip { font-size: 11.5px; padding: 6px 11px; }
  .assistant-text, .user-bubble .bubble-text { font-size: 13px; }
  .chat-input { padding: 10px; border-radius: 12px; }
  .tool-detail .detail-row pre { max-height: 140px; font-size: 10.5px; }
  .excess-value { font-size: 22px; }
}

.ai-main {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
.ai-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 4px;
}
.ai-header h1 {
  margin: 4px 0 0;
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.025em;
  color: var(--text-primary);
}

/* ─── 空态 ─── */
.chat-empty {
  text-align: center;
  padding: 60px 24px;
  border: 1px dashed var(--border-soft);
  border-radius: 14px;
  background: var(--surface-1);
}
.empty-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto 16px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(124, 58, 237, 0.18), rgba(6, 182, 212, 0.10));
  display: flex; align-items: center; justify-content: center;
}
.chat-empty h2 {
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 8px;
  letter-spacing: -0.02em;
}
.chat-empty p {
  margin: 0 auto 24px;
  max-width: 460px;
  line-height: 1.6;
}
.suggested-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  max-width: 700px;
  margin: 0 auto;
}
.prompt-chip {
  padding: 8px 14px;
  border-radius: 999px;
  background: var(--surface-2);
  border: 1px solid var(--border-soft);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
  color: var(--text-secondary);
}
.prompt-chip:hover {
  background: var(--accent-bg-soft);
  border-color: var(--border-accent);
  color: var(--accent);
}

/* ─── 聊天线程 ─── */
.chat-area {
  position: relative;
}
.chat-thread {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px 2px;
  max-height: 65vh;
  overflow-y: auto;
  scroll-behavior: smooth;
}
.jump-to-bottom {
  position: absolute;
  right: 12px;
  bottom: 16px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--card-bg);
  border: 1px solid var(--border-strong);
  color: var(--text-primary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-md);
  transition: transform 0.2s ease, border-color 0.2s ease, color 0.2s ease;
  z-index: 5;
}
.jump-to-bottom:hover {
  transform: translateY(-1px);
  border-color: var(--border-accent);
  color: var(--accent);
}
.msg {
  display: flex;
  flex-direction: column;
}
.msg.role-user { align-items: flex-end; }
.msg.role-assistant { align-items: stretch; }

.role-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
  font-weight: 500;
}

.user-bubble {
  max-width: 75%;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.user-bubble .bubble-text {
  padding: 11px 15px;
  border-radius: 16px 16px 4px 16px;
  background: var(--user-bubble-bg);
  border: 1px solid var(--user-bubble-border);
  color: var(--text-primary);
  font-size: 13.5px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  box-shadow: var(--shadow-sm);
}

.assistant-block {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* ─── 工具链 ─── */
.tool-chain {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 0;
}
.tool-step {
  border-left: 2px solid var(--border-soft);
  padding-left: 12px;
}
.tool-step.status-running { border-left-color: var(--accent); }
.tool-step.status-done { border-left-color: var(--success); }
.tool-step.status-error { border-left-color: var(--danger); }

.tool-step-head {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 0;
  user-select: none;
}
.tool-icon {
  display: inline-flex;
  width: 18px;
  height: 18px;
  align-items: center;
  justify-content: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 600;
}
.tool-icon.status-running {
  color: var(--accent);
  animation: spin 1.2s linear infinite;
}
.tool-icon.status-done { color: var(--success); }
.tool-icon.status-error { color: var(--danger); }
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.tool-name {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--accent);
  background: var(--accent-bg-soft);
  padding: 1px 7px;
  border-radius: 4px;
}
.tool-summary {
  font-size: 12px;
  color: var(--text-secondary);
  flex: 1;
}
.tool-expand-icon {
  color: var(--text-muted);
  opacity: 0.6;
}

.tool-detail {
  padding: 6px 0 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.detail-row {
  background: var(--surface-deep);
  border: 1px solid var(--border-soft);
  border-radius: 6px;
  padding: 8px 10px;
}
.detail-label {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.detail-row pre {
  margin: 0;
  font-size: 11px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--text-on-deep);
}

/* ─── 思考中 ─── */
.thinking-bubble {
  display: inline-flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: 12px;
  background: var(--accent-bg-soft);
  font-size: 12px;
  color: var(--text-secondary);
  width: fit-content;
}
.thinking-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent);
  margin-right: 4px;
  animation: pulse-dot 1.2s ease-in-out infinite;
}
.thinking-dot:nth-child(2) { animation-delay: 0.2s; }
.thinking-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes pulse-dot {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1.2); }
}

.inline-thinking {
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--surface-1);
  border: 1px solid var(--border-soft);
  font-size: 12px;
  color: var(--text-secondary);
  font-style: italic;
  line-height: 1.5;
  white-space: pre-wrap;
}

/* ─── 最终消息 ─── */
.assistant-text {
  padding: 14px 16px;
  border-radius: 16px 16px 16px 4px;
  background: var(--surface-1);
  border: 1px solid var(--border-soft);
  color: var(--text-primary);
  font-size: 13.5px;
  line-height: 1.65;
  box-shadow: var(--shadow-sm);
}

.error-bubble {
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--danger-bg);
  border: 1px solid var(--danger);
  color: var(--danger);
  font-size: 13px;
  display: flex; align-items: center; gap: 8px;
}

/* ─── 输入区 ─── */
.chat-input {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border-radius: 14px;
  background: var(--card-bg);
  border: 1px solid var(--border-soft);
  box-shadow: var(--shadow-sm);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.chat-input:focus-within {
  border-color: var(--border-accent);
  box-shadow: var(--shadow-glow);
}
.chat-input :deep(.n-input) {
  background: transparent;
}
.chat-input :deep(.n-input__textarea-el) {
  font-size: 13.5px;
  line-height: 1.55;
  padding: 4px 0;
}
.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* ─── DSL editor ─── */
:deep(.n-collapse-item__header) { padding: 10px 12px !important; }
:deep(.n-collapse-item__content-inner) { padding: 4px 12px 12px !important; }
.dsl-editor :deep(.n-input__textarea-el) {
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 13px !important;
  line-height: 1.65 !important;
}
.validation-error {
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--danger-bg);
  border: 1px solid var(--danger);
  color: var(--danger);
  font-size: 12px;
}

/* ─── 结果区 ─── */
.result-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.excess-card {
  background: linear-gradient(135deg, rgba(124, 58, 237, 0.06), rgba(6, 182, 212, 0.03)) !important;
  border: 1px solid var(--border-accent) !important;
}
.excess-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.excess-value {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.1;
  margin: 4px 0 4px;
}
.excess-value.good { color: var(--success); }
.excess-value.bad { color: var(--danger); }
.excess-value .unit {
  font-size: 14px;
  color: var(--text-muted);
  margin-left: 3px;
}
.tag-good {
  padding: 6px 12px;
  border-radius: 8px;
  background: var(--success-bg);
  color: var(--success);
  font-weight: 600;
  font-size: 12px;
}
.tag-bad {
  padding: 6px 12px;
  border-radius: 8px;
  background: var(--danger-bg);
  color: var(--danger);
  font-weight: 600;
  font-size: 12px;
}

/* ─── 右侧栏 ─── */
.ai-aside {
  display: flex;
  flex-direction: column;
  gap: 0;
  position: sticky;
  top: 0;
}

.aside-empty {
  text-align: center;
  padding: 16px 4px;
}

.model-card {
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--border-soft);
  margin-bottom: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  background: var(--surface-1);
}
.model-card:hover {
  border-color: var(--border-accent);
  background: var(--accent-bg-soft);
}
.model-card.selected {
  border-color: var(--border-accent);
  background: var(--accent-bg-soft);
  box-shadow: 0 0 0 1px var(--border-accent);
}
.model-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.model-radio {
  width: 16px; height: 16px;
  display: flex; align-items: center; justify-content: center;
}
.radio-on, .radio-off {
  width: 14px; height: 14px;
  border-radius: 50%;
  border: 1.5px solid var(--text-muted);
  position: relative;
}
.radio-on { border-color: var(--accent); }
.radio-on::after {
  content: '';
  position: absolute;
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--accent);
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
}
.model-card-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}
.model-card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  margin-left: 24px;
}

.tool-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border-soft);
}
.tool-info:last-child { border-bottom: none; }
.tool-info code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--accent);
}

.strategy-item {
  padding: 8px 0;
  border-bottom: 1px solid var(--border-soft);
  cursor: pointer;
  transition: color 0.15s ease;
}
.strategy-item:last-child { border-bottom: none; }
.strategy-item:hover { color: var(--accent); }

/* ─── 会话历史 ─── */
.session-item {
  display: flex;
  flex-direction: column;
  padding: 8px 10px;
  margin: 2px 4px;
  border-radius: 6px;
  cursor: pointer;
  position: relative;
  transition: background 0.15s ease;
}
.session-item:hover { background: var(--surface-1); }
.session-active {
  background: var(--accent-bg-soft);
  box-shadow: inset 0 0 0 1px var(--border-accent);
}
.session-title {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: 22px;
}
.session-meta {
  font-size: 10px;
  margin-top: 2px;
}
.session-del {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.15s ease, color 0.15s ease, background 0.15s ease;
}
.session-item:hover .session-del { opacity: 1; }
.session-del:hover { background: var(--danger-bg); color: var(--danger); }
</style>
