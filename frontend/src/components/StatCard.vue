<script setup lang="ts">
import { NCard, NIcon, NText } from 'naive-ui'
import { computed } from 'vue'

interface Props {
  label: string
  value: string | number
  hint?: string
  icon?: any
  color?: string
  prefix?: string
  suffix?: string
  /** 大号样式：用于 hero stat */
  hero?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  color: '#7c3aed',
  hero: false,
})

const formatted = computed(() => {
  if (typeof props.value === 'number') {
    if (props.value >= 1_000_000) return (props.value / 1_000_000).toFixed(2) + 'M'
    if (props.value >= 10_000) return (props.value / 1_000).toFixed(1) + 'K'
    return props.value.toLocaleString('en-US')
  }
  return props.value
})
</script>

<template>
  <NCard class="stat-card" :bordered="true" :class="{ hero }">
    <div class="stat-row">
      <div class="stat-text">
        <div class="stat-label">{{ label }}</div>
        <div class="stat-value mono" :class="{ 'gradient-text': hero }">
          <span v-if="prefix" class="stat-fix">{{ prefix }}</span>
          <span>{{ formatted }}</span>
          <span v-if="suffix" class="stat-fix">{{ suffix }}</span>
        </div>
        <div class="stat-hint muted" v-if="hint">{{ hint }}</div>
      </div>
      <div v-if="icon" class="stat-icon" :style="{
        background: `linear-gradient(135deg, ${color}33, ${color}11)`,
        color
      }">
        <NIcon :size="hero ? 28 : 22">
          <component :is="icon" />
        </NIcon>
      </div>
    </div>
    <div class="card-decoration" :style="{ background: color }" />
  </NCard>
</template>

<style scoped>
.stat-card {
  position: relative;
  overflow: hidden;
  transition: transform 0.18s ease, border-color 0.18s ease;
}
.stat-card:hover {
  transform: translateY(-2px);
}
.stat-card :deep(.n-card__content) {
  padding: 20px 22px;
}
.stat-card.hero :deep(.n-card__content) {
  padding: 26px 26px 24px;
}

.stat-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.stat-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stat-label {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  font-weight: 500;
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  line-height: 1.1;
}
.hero .stat-value {
  font-size: 40px;
}
.stat-fix {
  font-size: 14px;
  margin: 0 2px;
  color: var(--text-muted);
  font-weight: 500;
}
.stat-hint {
  font-size: 11px;
  margin-top: 4px;
  letter-spacing: 0.02em;
}
.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.hero .stat-icon {
  width: 56px;
  height: 56px;
}
.card-decoration {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  opacity: 0.4;
}
</style>
