import { ref, watch } from 'vue'
import { defineStore } from 'pinia'

export type ThemeMode = 'light' | 'dark'
export type PixelTheme = 'midnight' | 'amber' | 'jade'

const STORAGE_KEY = 'openclaw_theme'
const PIXEL_STORAGE_KEY = 'openclaw_pixel_theme'

export const useThemeStore = defineStore('theme', () => {
  const stored = localStorage.getItem(STORAGE_KEY) as ThemeMode | null
  const mode = ref<ThemeMode>(stored || 'dark')

  const pixelStored = localStorage.getItem(PIXEL_STORAGE_KEY) as PixelTheme | null
  const pixelTheme = ref<PixelTheme>(pixelStored || 'midnight')

  // Apply dark mode + pixel theme to <html>
  watch(mode, (val) => {
    localStorage.setItem(STORAGE_KEY, val)
    document.documentElement.setAttribute('data-theme', val)
  }, { immediate: true })

  watch(pixelTheme, (val) => {
    localStorage.setItem(PIXEL_STORAGE_KEY, val)
    document.documentElement.setAttribute('data-pixel-theme', val)
  }, { immediate: true })

  function toggle() {
    mode.value = mode.value === 'light' ? 'dark' : 'light'
  }

  function setMode(m: ThemeMode) {
    mode.value = m
  }

  function setPixelTheme(t: PixelTheme) {
    pixelTheme.value = t
  }

  function cyclePixelTheme() {
    const order: PixelTheme[] = ['midnight', 'amber', 'jade']
    const idx = order.indexOf(pixelTheme.value)
    pixelTheme.value = order[(idx + 1) % order.length] || 'midnight'
  }

  return { mode, pixelTheme, toggle, setMode, setPixelTheme, cyclePixelTheme }
})
