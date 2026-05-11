<script setup lang="ts">
import { onMounted, ref, computed, h, reactive } from 'vue'
import {
  NCard, NSpace, NTag, NInput, NButton, NIcon, NSelect,
  NText, NDivider, NAlert, NSpin, NRadio, NRadioGroup,
  useMessage, useDialog, NPopconfirm, NEmpty,
} from 'naive-ui'
import {
  CheckmarkCircleOutline, AlertCircleOutline, SparklesOutline,
  SaveOutline, FlashOutline, EyeOutline, EyeOffOutline, TrashOutline,
  AddCircleOutline, RadioButtonOnOutline, RadioButtonOffOutline,
} from '@vicons/ionicons5'
import {
  api, type AIConfigView, type AIModelInput, type ChatResp, AuthRequired,
} from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const message = useMessage()
const dialog = useDialog()

const loading = ref(true)
const saving = ref(false)
const view = ref<AIConfigView | null>(null)

// 表单：编辑中的模型列表
interface DraftModel {
  id?: string
  label: string
  format: 'openai' | 'anthropic'
  api_key: string         // 空 = 保留原 key
  api_key_masked?: string
  api_key_set: boolean
  model_id: string
  base_url: string
  show_key: boolean       // UI only
  testing: boolean        // UI only
  test_result?: { ok: boolean; message?: string; error?: string }
}

const drafts = ref<DraftModel[]>([])
const defaultId = ref<string>('')

async function load() {
  loading.value = true
  try {
    const r = await api.get<AIConfigView>('/settings/ai')
    view.value = r.data
    drafts.value = r.data.models.map(m => ({
      id: m.id,
      label: m.label,
      format: m.format,
      api_key: '',
      api_key_masked: m.api_key_masked,
      api_key_set: m.api_key_set,
      model_id: m.model_id,
      base_url: m.base_url,
      show_key: false,
      testing: false,
    }))
    defaultId.value = r.data.default_model_id
  } catch (e) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else message.error('加载设置失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)

function addModel(presetFormat: 'openai' | 'anthropic' = 'openai') {
  drafts.value.push({
    label: presetFormat === 'anthropic' ? 'Claude Haiku' : 'DeepSeek V4',
    format: presetFormat,
    api_key: '',
    api_key_set: false,
    model_id: presetFormat === 'anthropic' ? 'claude-3-5-haiku-20241022' : 'deepseek-chat',
    base_url: presetFormat === 'anthropic' ? '' : '',
    show_key: false,
    testing: false,
  })
}

async function deleteModel(idx: number) {
  const m = drafts.value[idx]
  if (m.id) {
    // 已保存的模型：调 DELETE，重新加载
    try {
      await api.delete(`/settings/ai/models/${m.id}`)
      message.success(`已删除 ${m.label}`)
      await load()
    } catch (e: any) {
      if (e instanceof AuthRequired) auth.requireLogin()
      else message.error(`删除失败：${e.message}`)
    }
  } else {
    // 仅在 drafts 里没保存的：直接 splice
    drafts.value.splice(idx, 1)
  }
}

async function save() {
  if (drafts.value.length === 0) {
    message.warning('至少添加一个模型')
    return
  }
  // 校验
  for (const m of drafts.value) {
    if (!m.label.trim()) {
      message.error('每个模型必须有 label')
      return
    }
    if (!m.model_id.trim()) {
      message.error(`模型 ${m.label!} 缺 model_id`)
      return
    }
  }
  saving.value = true
  try {
    const payload: AIModelInput[] = drafts.value.map(m => ({
      id: m.id,
      label: m.label.trim(),
      format: m.format,
      api_key: m.api_key,
      model_id: m.model_id.trim(),
      base_url: m.base_url.trim(),
    }))
    const r = await api.post<AIConfigView>('/settings/ai', {
      models: payload,
      default_model_id: defaultId.value,
    })
    view.value = r.data
    message.success('保存成功')
    await load()
  } catch (e: any) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else {
      const detail = e.response?.data?.detail || e.message
      message.error(`保存失败：${detail}`)
    }
  } finally {
    saving.value = false
  }
}

async function testModel(idx: number) {
  const m = drafts.value[idx]
  m.testing = true
  m.test_result = undefined
  try {
    const r = await api.post<ChatResp>('/settings/ai/test', {
      inline: {
        id: m.id,
        label: m.label,
        format: m.format,
        api_key: m.api_key,    // 空 → 后端自动用旧的
        model_id: m.model_id,
        base_url: m.base_url,
      },
      text: '帮我列出有哪些 universe，简短回答',
    }, { timeout: 60_000 })
    m.test_result = r.data.ok
      ? { ok: true, message: r.data.message || '✓ LLM 调通' }
      : { ok: false, error: r.data.error || '未知错误' }
    if (r.data.ok) message.success(`✓ ${m.label} 测试成功`)
    else message.error(`✗ 测试失败：${r.data.error}`)
  } catch (e: any) {
    if (e instanceof AuthRequired) auth.requireLogin()
    else {
      const detail = e.response?.data?.detail || e.message
      m.test_result = { ok: false, error: detail }
      message.error(`测试失败：${detail}`)
    }
  } finally {
    m.testing = false
  }
}

const formatOptions = [
  { label: 'OpenAI 兼容（OpenAI / DeepSeek / 智谱 / Moonshot 等）', value: 'openai' },
  { label: 'Anthropic（Claude）', value: 'anthropic' },
]

const totalConfigured = computed(() =>
  drafts.value.filter(m => m.api_key_set || m.api_key).length
)
</script>

<template>
  <div class="settings-root">
    <div class="page-head">
      <div>
        <div class="muted" style="font-size: 12px; letter-spacing: 0.18em">SETTINGS</div>
        <h1>设置</h1>
      </div>
    </div>

    <NSpin :show="loading">
      <NCard>
        <template #header>
          <NSpace align="center" :size="10">
            <NIcon size="18" color="#a78bfa"><SparklesOutline /></NIcon>
            <span>AI 模型</span>
            <NText depth="3" style="font-size: 12px; font-weight: 400">
              {{ drafts.length }} 个模型 · {{ totalConfigured }} 已配置
            </NText>
          </NSpace>
        </template>

        <NAlert type="info" :show-icon="false" style="margin-bottom: 20px; font-size: 12px">
          每个模型独立 label + 格式 + 端点。<strong>格式</strong>有两种：
          <code>openai</code>（OpenAI / DeepSeek / Moonshot 等）和 <code>anthropic</code>（Claude）。
          API key 留空 = 保留原值。<strong>测试按钮</strong>用当前表单的值跑（无需先保存）。
        </NAlert>

        <!-- 模型列表 -->
        <NEmpty v-if="drafts.length === 0" description="还没有配置任何模型" style="padding: 30px 0">
          <template #extra>
            <NSpace>
              <NButton @click="addModel('openai')" type="primary">
                <template #icon><NIcon><AddCircleOutline /></NIcon></template>
                添加 OpenAI 兼容
              </NButton>
              <NButton @click="addModel('anthropic')">
                <template #icon><NIcon><AddCircleOutline /></NIcon></template>
                添加 Anthropic
              </NButton>
            </NSpace>
          </template>
        </NEmpty>

        <div v-for="(m, idx) in drafts" :key="idx" class="model-row">
          <div class="model-row-head">
            <NSpace align="center" :size="10">
              <!-- 默认单选 -->
              <NIcon style="cursor: pointer; color: var(--accent)" size="20"
                @click="m.id && (defaultId = m.id)">
                <component :is="(m.id && defaultId === m.id) ? RadioButtonOnOutline : RadioButtonOffOutline" />
              </NIcon>
              <NInput v-model:value="m.label" placeholder="自定义名字（label）"
                style="width: 280px" autocomplete="off" />
              <NTag v-if="m.api_key_set" size="small" :bordered="false" type="success">
                <template #icon><NIcon><CheckmarkCircleOutline /></NIcon></template>
                已配置
              </NTag>
            </NSpace>
            <NSpace>
              <NButton size="small" tertiary :loading="m.testing" @click="testModel(idx)"
                :disabled="!m.model_id">
                <template #icon><NIcon><FlashOutline /></NIcon></template>
                测试
              </NButton>
              <NPopconfirm @positive-click="deleteModel(idx)">
                <template #trigger>
                  <NButton size="small" tertiary type="error">
                    <template #icon><NIcon><TrashOutline /></NIcon></template>
                  </NButton>
                </template>
                确定删除「{{ m.label }}」？
              </NPopconfirm>
            </NSpace>
          </div>

          <div class="model-row-body">
            <div class="form-row">
              <div class="form-label">格式</div>
              <NSelect v-model:value="m.format" :options="formatOptions" />
            </div>
            <div class="form-row">
              <div class="form-label">API Key</div>
              <NInput
                v-model:value="m.api_key"
                :type="m.show_key ? 'text' : 'password'"
                :placeholder="m.api_key_set
                  ? `已设置（${m.api_key_masked}）— 留空保留，输入新值替换`
                  : 'sk-...'"
                autocomplete="off"
              >
                <template #suffix>
                  <NIcon style="cursor: pointer" @click="m.show_key = !m.show_key">
                    <component :is="m.show_key ? EyeOffOutline : EyeOutline" />
                  </NIcon>
                </template>
              </NInput>
            </div>
            <div class="form-row">
              <div class="form-label">Model ID</div>
              <NInput v-model:value="m.model_id"
                :placeholder="m.format === 'anthropic' ? 'claude-3-5-haiku-20241022' : 'deepseek-chat / gpt-4o-mini / glm-4-plus'"
                autocomplete="off" />
            </div>
            <div class="form-row">
              <div class="form-label">Base URL（可选）</div>
              <NInput v-model:value="m.base_url"
                :placeholder="m.format === 'anthropic'
                  ? '留空 = 官方 (https://api.anthropic.com)'
                  : '留空 = OpenAI 官方；DeepSeek = https://api.deepseek.com；其他兼容厂商写完整 URL'"
                autocomplete="off" />
            </div>
            <NAlert v-if="m.test_result" :type="m.test_result.ok ? 'success' : 'error'"
              style="margin-top: 8px; font-size: 12px" :show-icon="true">
              {{ m.test_result.ok ? m.test_result.message : m.test_result.error }}
            </NAlert>
          </div>
        </div>

        <!-- 列表底部的 + 添加 -->
        <NDivider v-if="drafts.length > 0" style="margin: 16px 0" />
        <NSpace v-if="drafts.length > 0">
          <NButton size="small" @click="addModel('openai')">
            <template #icon><NIcon><AddCircleOutline /></NIcon></template>
            添加 OpenAI 兼容模型
          </NButton>
          <NButton size="small" @click="addModel('anthropic')">
            <template #icon><NIcon><AddCircleOutline /></NIcon></template>
            添加 Anthropic 模型
          </NButton>
        </NSpace>

        <NDivider style="margin: 20px 0" />

        <!-- 保存 -->
        <NSpace>
          <NButton type="primary" :loading="saving" @click="save" :disabled="drafts.length === 0">
            <template #icon><NIcon><SaveOutline /></NIcon></template>
            保存全部
          </NButton>
        </NSpace>
      </NCard>

      <!-- 服务信息 -->
      <NCard style="margin-top: 16px">
        <template #header>服务信息</template>
        <div class="info-row">
          <div class="info-label">当前用户</div>
          <div class="mono">{{ auth.username }}</div>
        </div>
        <div class="info-row">
          <div class="info-label">设置存储</div>
          <div class="mono muted">SQLite settings 表，key = ai.config（JSON）</div>
        </div>
        <div class="info-row">
          <div class="info-label">默认模型</div>
          <div class="mono">{{
            defaultId
              ? (drafts.find(m => m.id === defaultId)?.label || defaultId)
              : '（未选）'
          }}</div>
        </div>
      </NCard>
    </NSpin>
  </div>
</template>

<style scoped>
.settings-root {
  max-width: 920px;
  margin: 0 auto;
}
.page-head {
  margin-bottom: 24px;
}
.page-head h1 {
  margin: 6px 0 0;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.025em;
  line-height: 1.1;
}

.model-row {
  border: 1px solid var(--border-soft);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
  background: var(--surface-1);
}
.model-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.model-row-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.form-label {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  font-weight: 500;
  width: 130px;
  flex-shrink: 0;
}

.info-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-soft);
}
.info-row:last-child { border-bottom: none; }
.info-label {
  font-size: 12px;
  color: var(--text-muted);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

code {
  padding: 1px 6px;
  background: var(--accent-bg-soft);
  color: var(--accent);
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}
</style>
