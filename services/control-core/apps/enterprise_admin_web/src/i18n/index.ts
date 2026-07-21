import { createI18n } from 'vue-i18n'
import en from './locales/en'
import zh from './locales/zh'

const savedLocale = localStorage.getItem('locale') || 'zh'

const i18n = createI18n({
  legacy: false,
  locale: savedLocale,
  fallbackLocale: 'en',
  messages: {
    en,
    zh,
  },
})

export default i18n
