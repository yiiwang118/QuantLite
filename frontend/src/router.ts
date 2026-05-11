import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/lab'
  },
  {
    path: '/lab',
    name: 'lab',
    component: () => import('./views/Lab.vue'),
    meta: { title: 'AI 助手', icon: 'sparkles' }
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('./views/Dashboard.vue'),
    meta: { title: '概览', icon: 'grid' }
  },
  {
    path: '/symbols',
    name: 'symbols',
    component: () => import('./views/Symbols.vue'),
    meta: { title: '股票', icon: 'list' }
  },
  {
    path: '/symbols/:market/:symbol',
    name: 'symbol-detail',
    component: () => import('./views/SymbolDetail.vue'),
    meta: { title: '股票详情', hidden: true }
  },
  {
    path: '/strategies',
    name: 'strategies',
    component: () => import('./views/Strategies.vue'),
    meta: { title: '策略库', icon: 'library' }
  },
  {
    path: '/backtests',
    name: 'backtests',
    component: () => import('./views/Backtests.vue'),
    meta: { title: '回测历史', icon: 'time' }
  },
  {
    path: '/backtests/:id',
    name: 'backtest-detail',
    component: () => import('./views/BacktestDetail.vue'),
    meta: { title: '回测详情', hidden: true }
  },
  {
    path: '/data',
    name: 'data-ops',
    component: () => import('./views/DataOps.vue'),
    meta: { title: '数据操作', icon: 'cloud-download' }
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('./views/Settings.vue'),
    meta: { title: '设置', icon: 'settings' }
  }
]

export default createRouter({
  history: createWebHistory(),
  routes
})
