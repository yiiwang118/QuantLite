<script setup lang="ts">
import { onMounted, computed } from 'vue'
import {
  NConfigProvider, NMessageProvider, NDialogProvider,
  NLoadingBarProvider, NNotificationProvider,
  NGlobalStyle, darkTheme,
  zhCN, dateZhCN, enUS, dateEnUS,
  type GlobalThemeOverrides,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import AppLayout from '@/components/AppLayout.vue'
import LoginDialog from '@/components/LoginDialog.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const { locale } = useI18n()

const naiveLocale = computed(() => locale.value === 'en' ? enUS : zhCN)
const naiveDateLocale = computed(() => locale.value === 'en' ? dateEnUS : dateZhCN)

const overrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#7c3aed',
    primaryColorHover: '#8b5cf6',
    primaryColorPressed: '#6d28d9',
    primaryColorSuppl: '#a78bfa',
    infoColor: '#3b82f6',
    successColor: '#10b981',
    warningColor: '#f59e0b',
    errorColor: '#ef4444',
    bodyColor: 'transparent',
    cardColor: '#0e1124',
    modalColor: '#0e1124',
    popoverColor: '#141833',
    dividerColor: 'rgba(255,255,255,0.06)',
    borderColor: 'rgba(255,255,255,0.08)',
    hoverColor: 'rgba(255,255,255,0.04)',
    textColor1: '#f8fafc',
    textColor2: '#cbd5e1',
    textColor3: '#94a3b8',
    placeholderColor: '#64748b',
    fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
    fontFamilyMono: '"JetBrains Mono", "SF Mono", "Menlo", "Consolas", monospace',
    borderRadius: '10px',
    borderRadiusSmall: '6px',
  },
  Card: {
    color: '#0e1124',
    borderColor: 'rgba(255,255,255,0.06)',
    titleTextColor: '#f8fafc',
    titleFontWeight: '600',
  },
  Layout: {
    color: 'transparent',
    siderColor: 'rgba(14, 17, 36, 0.7)',
    headerColor: 'transparent',
    headerBorderColor: 'rgba(255,255,255,0.06)',
    siderBorderColor: 'rgba(255,255,255,0.06)',
  },
  Menu: {
    color: 'transparent',
    itemColorActive: 'rgba(124, 58, 237, 0.12)',
    itemColorActiveHover: 'rgba(124, 58, 237, 0.18)',
    itemTextColorActive: '#a78bfa',
    itemTextColorActiveHover: '#c4b5fd',
    itemIconColorActive: '#a78bfa',
    itemIconColorActiveHover: '#c4b5fd',
  },
  DataTable: {
    thColor: 'rgba(255,255,255,0.02)',
    tdColorHover: 'rgba(255,255,255,0.025)',
    thTextColor: '#94a3b8',
    borderColor: 'rgba(255,255,255,0.05)',
    thFontWeight: '500',
  },
}

onMounted(() => {
  if (!auth.username) auth.requireLogin()
})
</script>

<template>
  <NConfigProvider :theme="darkTheme" :theme-overrides="overrides"
    :locale="naiveLocale" :date-locale="naiveDateLocale">
    <NGlobalStyle />
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
