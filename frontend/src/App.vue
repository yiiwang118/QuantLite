<script setup lang="ts">
import { onMounted, computed, ref, watch, provide, type Ref } from 'vue'
import {
  NConfigProvider, NMessageProvider, NDialogProvider,
  NLoadingBarProvider, NNotificationProvider,
  darkTheme,
  zhCN, dateZhCN, enUS, dateEnUS,
  type GlobalThemeOverrides,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import AppLayout from '@/components/AppLayout.vue'
import LoginDialog from '@/components/LoginDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { applyTheme } from '@/theme-vars'

const auth = useAuthStore()
const { locale } = useI18n()

// ─── 主题（auto / dark / light）──────────────────────────
type ThemeMode = 'auto' | 'dark' | 'light'
const userTheme = ref<ThemeMode>(
  (localStorage.getItem('quant-lite-theme') as ThemeMode) || 'auto'
)
const osPrefersDark = ref(window.matchMedia('(prefers-color-scheme: dark)').matches)
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
  osPrefersDark.value = e.matches
})
const isDark = computed(() =>
  userTheme.value === 'dark' || (userTheme.value === 'auto' && osPrefersDark.value)
)
// JS 直写 CSS vars 到 documentElement style，inline 优先级最高
watch(isDark, (v) => applyTheme(v), { immediate: true })

function setTheme(t: ThemeMode) {
  userTheme.value = t
  localStorage.setItem('quant-lite-theme', t)
}
provide('theme-control', { userTheme, setTheme, isDark } as {
  userTheme: Ref<ThemeMode>
  setTheme: (t: ThemeMode) => void
  isDark: Ref<boolean>
})

const naiveTheme = computed(() => isDark.value ? darkTheme : null)

// ─── Naive UI locale ────────────────────────────────────
const naiveLocale = computed(() => locale.value === 'en' ? enUS : zhCN)
const naiveDateLocale = computed(() => locale.value === 'en' ? dateEnUS : dateZhCN)

// ─── Theme overrides ────────────────────────────────────

const sharedCommon = {
  primaryColor: '#7c3aed',
  primaryColorHover: '#8b5cf6',
  primaryColorPressed: '#6d28d9',
  primaryColorSuppl: '#a78bfa',
  infoColor: '#3b82f6',
  successColor: '#10b981',
  warningColor: '#f59e0b',
  errorColor: '#ef4444',
  fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
  fontFamilyMono: '"JetBrains Mono", "SF Mono", "Menlo", "Consolas", monospace',
  borderRadius: '12px',
  borderRadiusSmall: '8px',
}

const darkOverrides: GlobalThemeOverrides = {
  common: {
    ...sharedCommon,
    bodyColor: 'transparent',
    cardColor: '#0e1124',
    modalColor: '#0e1124',
    popoverColor: '#161a37',
    dividerColor: 'rgba(255,255,255,0.06)',
    borderColor: 'rgba(255,255,255,0.10)',
    hoverColor: 'rgba(255,255,255,0.04)',
    textColor1: '#f8fafc',
    textColor2: '#cbd5e1',
    textColor3: '#94a3b8',
    placeholderColor: '#64748b',
  },
  Card: {
    color: '#0e1124',
    borderColor: 'rgba(255,255,255,0.07)',
    titleTextColor: '#f8fafc',
    titleFontWeight: '600',
  },
  Layout: {
    color: 'transparent',
    siderColor: 'rgba(14, 17, 36, 0.65)',
    headerColor: 'transparent',
    headerBorderColor: 'rgba(255,255,255,0.06)',
    siderBorderColor: 'rgba(255,255,255,0.06)',
  },
  Menu: {
    color: 'transparent',
    itemColorActive: 'rgba(124, 58, 237, 0.14)',
    itemColorActiveHover: 'rgba(124, 58, 237, 0.20)',
    itemTextColorActive: '#a78bfa',
    itemTextColorActiveHover: '#c4b5fd',
    itemIconColorActive: '#a78bfa',
    itemIconColorActiveHover: '#c4b5fd',
  },
  DataTable: {
    thColor: 'rgba(255,255,255,0.02)',
    tdColorHover: 'rgba(255,255,255,0.03)',
    thTextColor: '#94a3b8',
    borderColor: 'rgba(255,255,255,0.06)',
    thFontWeight: '500',
  },
}

const lightOverrides: GlobalThemeOverrides = {
  common: {
    ...sharedCommon,
    primaryColorPressed: '#5b21b6',
    bodyColor: 'transparent',
    cardColor: '#ffffff',
    modalColor: '#ffffff',
    popoverColor: '#ffffff',
    dividerColor: 'rgba(15,23,42,0.08)',
    borderColor: 'rgba(15,23,42,0.12)',
    hoverColor: 'rgba(15,23,42,0.04)',
    textColor1: '#0f172a',
    textColor2: '#334155',
    textColor3: '#64748b',
    placeholderColor: '#94a3b8',
  },
  Card: {
    color: '#ffffff',
    borderColor: 'rgba(15,23,42,0.08)',
    titleTextColor: '#0f172a',
    titleFontWeight: '600',
  },
  Layout: {
    color: 'transparent',
    siderColor: 'rgba(255, 255, 255, 0.72)',
    headerColor: 'rgba(255, 255, 255, 0.55)',
    headerBorderColor: 'rgba(15,23,42,0.08)',
    siderBorderColor: 'rgba(15,23,42,0.08)',
    textColor: '#0f172a',
  },
  Menu: {
    color: 'transparent',
    itemTextColor: '#475569',
    itemIconColor: '#64748b',
    itemColorHover: 'rgba(15,23,42,0.04)',
    itemColorActive: 'rgba(124, 58, 237, 0.10)',
    itemColorActiveHover: 'rgba(124, 58, 237, 0.16)',
    itemTextColorActive: '#6d28d9',
    itemTextColorActiveHover: '#7c3aed',
    itemIconColorActive: '#6d28d9',
    itemIconColorActiveHover: '#7c3aed',
  },
  DataTable: {
    thColor: 'rgba(15,23,42,0.03)',
    tdColor: '#ffffff',
    tdColorHover: 'rgba(15,23,42,0.03)',
    thTextColor: '#64748b',
    tdTextColor: '#0f172a',
    borderColor: 'rgba(15,23,42,0.06)',
    thFontWeight: '500',
  },
  Tag: {
    color: 'rgba(15,23,42,0.05)',
    textColor: '#334155',
    border: '1px solid rgba(15,23,42,0.10)',
  },
  Input: {
    color: '#ffffff',
    colorFocus: '#ffffff',
    border: '1px solid rgba(15,23,42,0.12)',
    borderHover: 'rgba(124,58,237,0.45)',
    borderFocus: '#7c3aed',
    placeholderColor: '#94a3b8',
    textColor: '#0f172a',
  },
  Select: {
    peers: {
      InternalSelection: {
        textColor: '#0f172a',
        placeholderColor: '#94a3b8',
        color: '#ffffff',
        border: '1px solid rgba(15,23,42,0.12)',
      },
    },
  },
  Dropdown: {
    color: '#ffffff',
    borderColor: 'rgba(15,23,42,0.10)',
    optionTextColor: '#334155',
    optionColorHover: 'rgba(15,23,42,0.04)',
  },
}

const overrides = computed(() => isDark.value ? darkOverrides : lightOverrides)

onMounted(() => {
  if (!auth.username) auth.requireLogin()
})
</script>

<template>
  <NConfigProvider :theme="naiveTheme" :theme-overrides="overrides"
    :locale="naiveLocale" :date-locale="naiveDateLocale">
    <NLoadingBarProvider>
      <NDialogProvider>
        <NNotificationProvider>
          <NMessageProvider>
            <AppLayout>
              <RouterView v-slot="{ Component, route }">
                <Transition name="fade" mode="out-in">
                  <KeepAlive :max="10">
                    <component :is="Component" v-if="auth.username" :key="route.fullPath" />
                  </KeepAlive>
                </Transition>
              </RouterView>
              <div v-if="!auth.username" class="login-placeholder">
                <div class="muted" style="letter-spacing: 0.2em; font-size: 12px;">
                  请先登录
                </div>
              </div>
            </AppLayout>
            <LoginDialog />
          </NMessageProvider>
        </NNotificationProvider>
      </NDialogProvider>
    </NLoadingBarProvider>
  </NConfigProvider>
</template>

<style scoped>
.login-placeholder {
  text-align: center;
  padding: 120px;
}
</style>
