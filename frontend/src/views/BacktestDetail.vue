<script setup lang="ts">
/** 回测详情页 — 重定向到 Lab?backtest_id=X，复用同一展示组件。 */
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

onMounted(() => {
  router.replace({ name: 'lab', query: { backtest_id: route.params.id as string } })
})
</script>

<template>
  <div />
</template>
