<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent, DataZoomComponent,
  MarkLineComponent, AxisPointerComponent, MarkPointComponent
} from 'echarts/components'

use([
  CanvasRenderer, LineChart,
  GridComponent, TooltipComponent, LegendComponent, DataZoomComponent,
  MarkLineComponent, AxisPointerComponent, MarkPointComponent,
])

const props = defineProps<{
  navCurve: [string, number][]
  benchmarkCurve?: [string, number][]
}>()

// 从 CSS 变量读颜色，主题切换自动适配
function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

const option = computed(() => {
  // 触发响应式更新（即使没用到 props 也强制重算）
  void props.navCurve.length

  const dates = props.navCurve.map(p => p[0])
  const values = props.navCurve.map(p => p[1])
  const benchValues = props.benchmarkCurve
    ? props.benchmarkCurve.map(p => p[1])
    : null

  // 回撤
  let peak = values[0] || 1.0
  const dd = values.map(v => {
    if (v > peak) peak = v
    return peak > 0 ? -((peak - v) / peak) * 100 : 0
  })

  const axisLabel = cssVar('--chart-axis-label', '#94a3b8')
  const axisLine = cssVar('--chart-axis-line', 'rgba(255,255,255,0.10)')
  const splitLine = cssVar('--chart-split-line', 'rgba(255,255,255,0.05)')
  const tooltipBg = cssVar('--chart-tooltip-bg', 'rgba(20,24,51,0.95)')
  const tooltipText = cssVar('--chart-tooltip-text', '#f8fafc')

  const seriesNav: any[] = [
    {
      name: '策略 NAV', type: 'line', data: values, smooth: false,
      symbol: 'none', sampling: 'lttb',
      lineStyle: { width: 2, color: '#a78bfa' },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(167, 139, 250, 0.35)' },
            { offset: 1, color: 'rgba(167, 139, 250, 0.02)' },
          ],
        },
      },
      markLine: {
        silent: true, symbol: 'none',
        lineStyle: { color: axisLine, type: 'dashed', width: 1 },
        data: [{ yAxis: 1.0, label: { color: axisLabel, fontSize: 10, formatter: 'NAV=1.0' } }],
      },
    },
  ]
  if (benchValues) {
    seriesNav.push({
      name: '基准（等权全持）', type: 'line', data: benchValues,
      symbol: 'none', sampling: 'lttb',
      lineStyle: { width: 1.5, color: cssVar('--text-muted', '#94a3b8'), type: 'dashed' },
    })
  }

  return {
    animation: false,
    backgroundColor: 'transparent',
    legend: {
      data: benchValues ? ['策略 NAV', '基准（等权全持）', '回撤'] : ['策略 NAV', '回撤'],
      top: 6,
      textStyle: { color: axisLabel, fontSize: 11 },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: tooltipBg,
      borderWidth: 0,
      textStyle: { color: tooltipText, fontSize: 12 },
      formatter: (params: any[]) => {
        const navP = params.find((p: any) => p.seriesName === '策略 NAV')
        const benchP = params.find((p: any) => p.seriesName === '基准（等权全持）')
        const ddP = params.find((p: any) => p.seriesName === '回撤')
        let html = `<div style="font-weight:600">${params[0].axisValue}</div>`
        if (navP) html += `<div>策略 <span style="font-family: monospace; color: #a78bfa">${navP.data.toFixed(4)}</span></div>`
        if (benchP) html += `<div>基准 <span style="font-family: monospace; color: #94a3b8">${benchP.data.toFixed(4)}</span></div>`
        if (navP && benchP) {
          const ex = ((navP.data - benchP.data) * 100).toFixed(2)
          const color = (navP.data >= benchP.data) ? '#10b981' : '#ef4444'
          html += `<div>超额 <span style="font-family: monospace; color: ${color}">${ex.startsWith('-') ? '' : '+'}${ex} pp</span></div>`
        }
        if (ddP) html += `<div>回撤 <span style="font-family: monospace; color: #ef4444">${ddP.data.toFixed(2)}%</span></div>`
        return html
      },
    },
    grid: [
      { left: 60, right: 24, top: 36, height: '62%' },
      { left: 60, right: 24, top: '74%', height: '16%' },
    ],
    xAxis: [
      {
        type: 'category', data: dates, boundaryGap: false,
        axisLabel: { fontSize: 11, color: axisLabel },
        axisLine: { lineStyle: { color: axisLine } },
      },
      {
        type: 'category', data: dates, gridIndex: 1, boundaryGap: false,
        axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false },
      },
    ],
    yAxis: [
      {
        type: 'value', scale: true, name: 'NAV',
        nameTextStyle: { color: axisLabel, fontSize: 11 },
        axisLabel: {
          fontSize: 11, color: axisLabel,
          formatter: (v: number) => v.toFixed(2),
        },
        splitLine: { lineStyle: { color: splitLine } },
      },
      {
        type: 'value', gridIndex: 1, scale: true, name: '回撤 %',
        nameTextStyle: { color: axisLabel, fontSize: 10 },
        max: 0,
        axisLabel: {
          fontSize: 10, color: axisLabel,
          formatter: (v: number) => v.toFixed(0) + '%',
        },
        splitLine: { lineStyle: { color: splitLine } },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], top: '93%', height: 18,
        textStyle: { color: axisLabel, fontSize: 10 } },
    ],
    series: [
      ...seriesNav,
      {
        name: '回撤', type: 'line', data: dd, smooth: false,
        symbol: 'none', sampling: 'lttb',
        xAxisIndex: 1, yAxisIndex: 1,
        lineStyle: { width: 1, color: '#ef4444' },
        areaStyle: { color: 'rgba(239, 68, 68, 0.18)' },
      },
    ],
  }
})
</script>

<template>
  <VChart v-if="navCurve.length > 0" :option="option" autoresize
    style="height: 520px;" />
  <div v-else class="muted" style="height: 520px; display: flex; align-items: center; justify-content: center">
    暂无净值数据
  </div>
</template>
