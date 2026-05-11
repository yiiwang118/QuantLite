<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent } from 'echarts/components'

use([CanvasRenderer, LineChart, GridComponent])

const props = withDefaults(defineProps<{
  data: number[]
  width?: number
  height?: number
  market?: 'cn' | 'us' | string
}>(), {
  width: 120,
  height: 36,
  market: 'cn',
})

const option = computed(() => {
  const data = props.data
  if (data.length < 2) return null
  const first = data[0]
  const last = data[data.length - 1]
  const isUp = last >= first
  // 中国市场红涨绿跌，美股反之
  const positive = props.market === 'us'
    ? (isUp ? '#10b981' : '#ef4444')
    : (isUp ? '#ef4444' : '#10b981')

  return {
    animation: false,
    grid: { left: 1, right: 1, top: 2, bottom: 2 },
    xAxis: { type: 'category', show: false, boundaryGap: false, data: data.map((_, i) => i) },
    yAxis: { type: 'value', show: false, scale: true },
    series: [{
      type: 'line',
      data,
      smooth: true,
      symbol: 'none',
      lineStyle: { color: positive, width: 1.5 },
      areaStyle: {
        opacity: 0.18,
        color: positive,
      },
    }],
    tooltip: { show: false },
  }
})
</script>

<template>
  <VChart v-if="option" :option="option" :init-options="{ renderer: 'canvas' }"
    :style="{ width: width + 'px', height: height + 'px' }" />
  <span v-else class="muted" style="font-size: 11px">—</span>
</template>
