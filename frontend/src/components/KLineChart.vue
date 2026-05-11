<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { CandlestickChart, BarChart, LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent, DataZoomComponent,
  TitleComponent, MarkLineComponent, AxisPointerComponent
} from 'echarts/components'
import type { Candle } from '@/api/client'

use([
  CanvasRenderer, CandlestickChart, BarChart, LineChart,
  GridComponent, TooltipComponent, LegendComponent, DataZoomComponent,
  TitleComponent, MarkLineComponent, AxisPointerComponent
])

const props = defineProps<{
  candles: Candle[]
  symbol: string
  market: string
}>()

// 中国市场用红涨绿跌；美股用绿涨红跌
const upColor = computed(() => props.market === 'cn' ? '#d03050' : '#18a058')
const downColor = computed(() => props.market === 'cn' ? '#18a058' : '#d03050')

const option = computed(() => {
  const dates = props.candles.map(c => c.date)
  const ohlc = props.candles.map(c => [c.open, c.close, c.low, c.high])
  const volumes = props.candles.map((c, i) => [
    i,
    c.volume,
    c.close >= c.open ? 1 : -1
  ])

  // MA 指标
  const closes = props.candles.map(c => c.close)
  const ma = (n: number) => closes.map((_, i) =>
    i < n - 1 ? '-' : (closes.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n).toFixed(2)
  )

  return {
    animation: false,
    backgroundColor: 'transparent',
    legend: {
      data: ['K线', 'MA5', 'MA20', 'MA60'],
      top: 8,
      textStyle: { fontSize: 11 }
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(50, 50, 50, 0.92)',
      textStyle: { color: '#fff', fontSize: 12 },
      borderWidth: 0
    },
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      label: { backgroundColor: '#777' }
    },
    grid: [
      { left: 56, right: 24, top: 50, height: '60%' },
      { left: 56, right: 24, top: '76%', height: '14%' }
    ],
    xAxis: [
      {
        type: 'category', data: dates, scale: true, boundaryGap: false,
        axisLine: { onZero: false }, splitLine: { show: false },
        axisLabel: { fontSize: 11 }
      },
      {
        type: 'category', gridIndex: 1, data: dates, scale: true, boundaryGap: false,
        axisLine: { onZero: false }, axisTick: { show: false },
        splitLine: { show: false }, axisLabel: { show: false }
      }
    ],
    yAxis: [
      {
        scale: true, splitArea: { show: true },
        axisLabel: { fontSize: 11 }
      },
      {
        gridIndex: 1, scale: true, splitNumber: 2,
        axisLabel: { show: false }, axisLine: { show: false },
        axisTick: { show: false }, splitLine: { show: false }
      }
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 70, end: 100 },
      { show: true, xAxisIndex: [0, 1], type: 'slider', top: '93%', height: 18, start: 70, end: 100 }
    ],
    series: [
      {
        name: 'K线', type: 'candlestick', data: ohlc,
        itemStyle: {
          color: upColor.value, color0: downColor.value,
          borderColor: upColor.value, borderColor0: downColor.value
        }
      },
      {
        name: 'MA5', type: 'line', data: ma(5), smooth: true, symbol: 'none',
        lineStyle: { width: 1, color: '#f0a020' }
      },
      {
        name: 'MA20', type: 'line', data: ma(20), smooth: true, symbol: 'none',
        lineStyle: { width: 1, color: '#2080f0' }
      },
      {
        name: 'MA60', type: 'line', data: ma(60), smooth: true, symbol: 'none',
        lineStyle: { width: 1, color: '#a020f0' }
      },
      {
        name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
        data: volumes,
        itemStyle: {
          color: (params: any) => params.data[2] > 0 ? upColor.value : downColor.value
        }
      }
    ]
  }
})
</script>

<template>
  <VChart v-if="candles.length > 0" :option="option" autoresize style="height: 480px;" />
  <div v-else class="empty muted">暂无行情数据</div>
</template>

<style scoped>
.empty {
  height: 480px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}
</style>
