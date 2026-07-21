import { ref, watch } from 'vue'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './variables.css'

type Theme = 'light' | 'dark'

const STORAGE_KEY = 'agent_admin_theme'

const theme = ref<Theme>(loadTheme())

function loadTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') {
    return stored
  }
  // Default to system preference
  if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark'
  }
  return 'light'
}

function applyTheme(t: Theme) {
  const html = document.documentElement
  if (t === 'dark') {
    html.classList.add('dark')
  } else {
    html.classList.remove('dark')
  }
}

// Apply on initial load
applyTheme(theme.value)

watch(theme, (val) => {
  applyTheme(val)
  localStorage.setItem(STORAGE_KEY, val)
})

export function useTheme() {
  function toggleTheme() {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
  }

  return {
    theme,
    toggleTheme,
  }
}
