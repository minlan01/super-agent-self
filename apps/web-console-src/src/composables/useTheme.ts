import { computed } from 'vue'
import { useThemeStore } from '@/stores/theme'
import type { PixelTheme } from '@/stores/theme'

/**
 * Bridge between Pinia theme store and CSS custom properties.
 * When pixelTheme changes, we set data-theme attribute on <html>
 * to trigger pixel-tokens.css variable overrides.
 *
 * The Naive UI themeOverrides are handled by usePixelTheme.ts and
 * applied via NConfigProvider in App.vue.
 */

export function useTheme() {
  const themeStore = useThemeStore()

  const isDark = computed(() => themeStore.mode === 'dark')
  const pixelTheme = computed(() => themeStore.pixelTheme)

  /** Map pixel theme name to CSS data-theme value */
  const cssDataTheme = computed<PixelTheme>(() => {
    return pixelTheme.value
  })

  return {
    mode: computed(() => themeStore.mode),
    isDark,
    pixelTheme,
    cssDataTheme,
    toggle: themeStore.toggle,
    setMode: themeStore.setMode,
    setPixelTheme: themeStore.setPixelTheme,
    cyclePixelTheme: themeStore.cyclePixelTheme,
  }
}
