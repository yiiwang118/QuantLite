<script setup lang="ts">
import { computed, h, inject, onMounted, ref, type Ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NIcon } from 'naive-ui'
import {
  GridOutline, ListOutline, CloudDownloadOutline, LogOutOutline,
  TrendingUpOutline, EllipsisHorizontal, FlaskOutline, LibraryOutline,
  TimeOutline, SettingsOutline, SparklesOutline, LanguageOutline,
  SunnyOutline, MoonOutline, DesktopOutline,
} from '@vicons/ionicons5'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api/client'
import { setLocale } from '@/i18n'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const { t, locale } = useI18n()

type ThemeMode = 'auto' | 'dark' | 'light'
const themeControl = inject<{
  userTheme: Ref<ThemeMode>
  setTheme: (t: ThemeMode) => void
  isDark: Ref<boolean>
}>('theme-control')!

const iconMap: Record<string, any> = {
  grid: GridOutline,
  list: ListOutline,
  'cloud-download': CloudDownloadOutline,
  flask: FlaskOutline,
  library: LibraryOutline,
  time: TimeOutline,
  settings: SettingsOutline,
  sparkles: SparklesOutline,
}

// Route name → i18n key
const routeI18nKey: Record<string, string> = {
  'lab': 'nav.lab',
  'dashboard': 'nav.dashboard',
  'symbols': 'nav.symbols',
  'symbol-detail': 'nav.symbolDetail',
  'strategies': 'nav.strategies',
  'backtests': 'nav.backtests',
  'data-ops': 'nav.dataOps',
  'settings': 'nav.settings',
}

const menuOptions = computed(() =>
  router.getRoutes()
    .filter(r => r.meta?.title && !r.meta?.hidden)
    .map(r => ({
      label: () => t(routeI18nKey[r.name as string] || (r.meta!.title as string)),
      key: r.name as string,
      icon: () => h(NIcon, null, { default: () => h(iconMap[r.meta!.icon as string] ?? GridOutline) }),
    }))
)

const activeKey = computed(() => {
  const r = route.matched.find(m => m.meta?.title && !m.meta?.hidden)
  return (r?.name ?? route.name) as string
})

const currentPageTitle = computed(() => {
  const name = route.name as string
  const key = routeI18nKey[name]
  return key ? t(key) : (route.meta?.title as string || '')
})

function onMenuSelect(key: string) {
  router.push({ name: key })
}

// ─── 用户菜单 ───
const userOptions = computed(() => [
  {
    label: t('topbar.logout'),
    key: 'logout',
    icon: () => h(NIcon, null, { default: () => h(LogOutOutline) }),
  },
])

function onUserAction(key: string) {
  if (key === 'logout') {
    auth.logout()
    auth.requireLogin()
  }
}

// ─── 语言切换 ───
const langOptions = [
  { label: '简体中文', key: 'zh' },
  { label: 'English', key: 'en' },
]
function onLangAction(key: string) {
  setLocale(key as any)
}

// ─── 主题切换 ───
const themeOptions = computed(() => [
  { label: t('topbar.themeAuto'), key: 'auto', icon: () => h(NIcon, null, { default: () => h(DesktopOutline) }) },
  { label: t('topbar.themeLight'), key: 'light', icon: () => h(NIcon, null, { default: () => h(SunnyOutline) }) },
  { label: t('topbar.themeDark'), key: 'dark', icon: () => h(NIcon, null, { default: () => h(MoonOutline) }) },
])
function onThemeAction(key: string) {
  themeControl.setTheme(key as ThemeMode)
}
const themeIcon = computed(() => {
  if (themeControl.userTheme.value === 'auto') return DesktopOutline
  return themeControl.isDark.value ? MoonOutline : SunnyOutline
})

// ─── 状态栏数据 ───
const status = ref<{ symbols: number; size_mb: number } | null>(null)
onMounted(async () => {
  if (!auth.username) return
  try {
    const r = await api.get('/overview')
    const totalSize = Object.values(r.data.cache).reduce((s: number, c: any) => s + (c.size_mb || 0), 0)
    status.value = { symbols: r.data.db.symbols_total, size_mb: +totalSize.toFixed(2) }
  } catch {}
})
</script>

<template>
  <NLayout has-sider style="height: 100vh">
    <NLayoutSider bordered :width="240" content-style="display: flex; flex-direction: column">
      <div class="brand">
        <div class="brand-logo">
          <NIcon size="22" color="white"><TrendingUpOutline /></NIcon>
        </div>
        <div>
          <div class="brand-name gradient-text">{{ t('brand.name') }}</div>
          <div class="brand-tagline">{{ t('brand.tagline') }} · v0.1</div>
        </div>
      </div>

      <NMenu :options="menuOptions" :value="activeKey" @update:value="onMenuSelect"
        :indent="20" style="flex: 1; padding: 8px 8px;" />

      <div class="sider-status" v-if="status">
        <div class="status-row">
          <span class="dot-live" />
          <NText depth="2" style="font-size: 11px; letter-spacing: 0.05em;">SERVICE LIVE</NText>
        </div>
        <div class="status-stats mono">
          <span>{{ status.symbols }} symbols</span>
          <span class="muted">·</span>
          <span>{{ status.size_mb }} MB</span>
        </div>
      </div>
    </NLayoutSider>

    <NLayout style="background: transparent">
      <NLayoutHeader class="topbar">
        <div class="topbar-left">
          <div class="topbar-title">{{ currentPageTitle }}</div>
          <NTag v-if="route.meta?.hidden" size="small" :bordered="false"
            :style="{ background: 'var(--accent-bg-soft)', color: 'var(--accent)' }">
            详情
          </NTag>
        </div>
        <NSpace align="center" :size="10">
          <!-- 语言切换 -->
          <NDropdown :options="langOptions" trigger="click" @select="onLangAction" placement="bottom-end">
            <NButton quaternary size="small">
              <template #icon><NIcon><LanguageOutline /></NIcon></template>
              {{ locale === 'en' ? 'EN' : '中文' }}
            </NButton>
          </NDropdown>
          <!-- 主题切换 -->
          <NDropdown :options="themeOptions" trigger="click" @select="onThemeAction" placement="bottom-end">
            <NButton quaternary size="small" circle :title="t('topbar.theme')">
              <template #icon><NIcon><component :is="themeIcon" /></NIcon></template>
            </NButton>
          </NDropdown>
          <!-- 用户 -->
          <div class="user-chip">
            <NAvatar :size="26" round
              style="background: linear-gradient(135deg, #7c3aed, #06b6d4); font-weight: 600">
              {{ auth.username?.slice(0, 1).toUpperCase() }}
            </NAvatar>
            <NText depth="1" style="font-weight: 500">{{ auth.username }}</NText>
          </div>
          <NDropdown :options="userOptions" trigger="click" @select="onUserAction" placement="bottom-end">
            <NButton quaternary circle size="small">
              <template #icon><NIcon><EllipsisHorizontal /></NIcon></template>
            </NButton>
          </NDropdown>
        </NSpace>
      </NLayoutHeader>

      <NLayoutContent class="main-content"
        content-style="padding: 28px 32px; min-height: 0; overflow: auto; background: transparent"
        :native-scrollbar="false">
        <slot />
      </NLayoutContent>
    </NLayout>
  </NLayout>
</template>

<style scoped>
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 22px 20px 18px;
  border-bottom: 1px solid var(--border-soft);
}
.brand-logo {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: var(--brand-grad);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow:
    0 1px 2px rgba(124, 58, 237, 0.20),
    0 8px 24px rgba(124, 58, 237, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.20);
  position: relative;
}
.brand-logo::after {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: 14px;
  background: var(--brand-grad);
  filter: blur(14px);
  opacity: 0.35;
  z-index: -1;
}
.brand-name {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.1;
}
.brand-tagline {
  font-size: 10.5px;
  color: var(--text-muted);
  letter-spacing: 0.10em;
  margin-top: 4px;
  text-transform: uppercase;
}

.sider-status {
  margin: 12px 14px 16px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--surface-1);
  border: 1px solid var(--border-soft);
}
.status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.status-stats {
  display: flex;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 32px;
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid var(--border-soft);
  position: sticky;
  top: 0;
  z-index: 10;
}
.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.topbar-title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 12px 4px 4px;
  border-radius: 999px;
  background: var(--surface-1);
  border: 1px solid var(--border-soft);
  color: var(--text-primary);
}
</style>
