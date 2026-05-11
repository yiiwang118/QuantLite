<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NIcon, NText } from 'naive-ui'

interface Props {
  label: string
  value: number
  /** 'pct' = 显示成百分比；'num' = 普通数字；'pct_neg_is_bad' = 百分比，负数红色 */
  format: 'pct' | 'num' | 'ratio'
  /** 用于上色：'up_good' = 正数绿色（夏普/收益）；'up_bad' = 正数红色（回撤/波动）；'neutral' */
  color: 'up_good' | 'up_bad' | 'neutral'
  hint?: string
}
const props = defineProps<Props>()

const formatted = computed(() => {
  if (props.format === 'pct') {
    return (props.value * 100).toFixed(2) + '%'
  }
  if (props.format === 'ratio') {
    return props.value.toFixed(3)
  }
  return props.value.toFixed(2)
})

const colorClass = computed(() => {
  if (props.color === 'neutral') return ''
  if (props.color === 'up_good') {
    return props.value > 0 ? 'good' : props.value < 0 ? 'bad' : ''
  }
  if (props.color === 'up_bad') {
    return props.value > 0.01 ? 'bad' : ''  // 回撤永远是正，但越大越糟
  }
  return ''
})

const valueWithSign = computed(() => {
  if (props.format === 'pct' || props.format === 'ratio') {
    if (props.value > 0 && (props.color === 'up_good')) return '+' + formatted.value
  }
  return formatted.value
})
</script>

<template>
  <NCard class="metric-card" hoverable>
    <div class="metric-label">{{ label }}</div>
    <div class="metric-value mono" :class="colorClass">{{ valueWithSign }}</div>
    <div class="metric-hint muted" v-if="hint">{{ hint }}</div>
  </NCard>
</template>

<style scoped>
.metric-card :deep(.n-card__content) {
  padding: 18px 20px;
}
.metric-label {
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
  font-weight: 500;
  margin-bottom: 8px;
}
.metric-value {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  line-height: 1.1;
}
.metric-value.good { color: var(--success); }
.metric-value.bad { color: var(--danger); }
.metric-hint {
  font-size: 11px;
  margin-top: 6px;
}
</style>
