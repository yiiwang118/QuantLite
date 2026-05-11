import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { i18n } from './i18n'
import { applyTheme } from './theme-vars'
import './style.css'

// HTML lang
document.documentElement.lang = (i18n.global.locale.value as string) === 'zh' ? 'zh-CN' : 'en'

// 主题：JS 直接 setProperty 写 CSS vars 到 documentElement，inline style 永远赢
const savedTheme = (localStorage.getItem('quant-lite-theme') as 'auto' | 'dark' | 'light') || 'auto'
const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
const initialDark = savedTheme === 'dark' || (savedTheme === 'auto' && prefersDark)
applyTheme(initialDark)

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(i18n)
app.mount('#app')
