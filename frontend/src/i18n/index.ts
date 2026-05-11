import { createI18n } from 'vue-i18n'
import zh from './zh'
import en from './en'

export type LocaleCode = 'zh' | 'en'
const LOCALE_KEY = 'quant-lite-lang'

function getInitialLocale(): LocaleCode {
  const saved = localStorage.getItem(LOCALE_KEY) as LocaleCode | null
  if (saved === 'zh' || saved === 'en') return saved
  // 默认从浏览器语言推断
  if (navigator.language.toLowerCase().startsWith('zh')) return 'zh'
  return 'en'
}

export const i18n = createI18n({
  legacy: false,
  locale: getInitialLocale(),
  fallbackLocale: 'zh',
  messages: { zh, en },
})

export function setLocale(loc: LocaleCode) {
  i18n.global.locale.value = loc
  localStorage.setItem(LOCALE_KEY, loc)
  document.documentElement.lang = loc === 'zh' ? 'zh-CN' : 'en'
}

export function currentLocale(): LocaleCode {
  return i18n.global.locale.value as LocaleCode
}
