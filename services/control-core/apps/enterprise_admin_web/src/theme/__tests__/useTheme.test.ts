import { describe, it, expect, beforeEach, vi } from 'vitest'
import { nextTick } from 'vue'

// We need to isolate the module for each test since theme state is module-level.
// Use vi.resetModules() to get fresh imports each time.

describe('useTheme', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
    document.documentElement.classList.remove('dark')
  })

  it('should return a theme ref', async () => {
    localStorage.setItem('agent_admin_theme', 'light')

    vi.doMock('element-plus/theme-chalk/dark/css-vars.css', () => ({}))
    vi.doMock('../variables.css', () => ({}))

    const { useTheme } = await import('../index')
    const { theme } = useTheme()
    expect(theme.value).toBeDefined()
    expect(['light', 'dark']).toContain(theme.value)
  })

  it('should toggle between light and dark', async () => {
    localStorage.setItem('agent_admin_theme', 'light')

    vi.doMock('element-plus/theme-chalk/dark/css-vars.css', () => ({}))
    vi.doMock('../variables.css', () => ({}))

    const { useTheme } = await import('../index')
    const { theme, toggleTheme } = useTheme()
    expect(theme.value).toBe('light')
    toggleTheme()
    await nextTick()
    expect(theme.value).toBe('dark')
    toggleTheme()
    await nextTick()
    expect(theme.value).toBe('light')
  })

  it('should persist theme to localStorage on toggle', async () => {
    localStorage.setItem('agent_admin_theme', 'light')

    vi.doMock('element-plus/theme-chalk/dark/css-vars.css', () => ({}))
    vi.doMock('../variables.css', () => ({}))

    const { useTheme } = await import('../index')
    const { toggleTheme } = useTheme()
    toggleTheme()
    await nextTick()
    expect(localStorage.getItem('agent_admin_theme')).toBe('dark')
  })

  it('should use system preference when no stored value', async () => {
    // Remove any stored value
    localStorage.removeItem('agent_admin_theme')

    // Mock matchMedia to prefer dark
    const originalMatchMedia = window.matchMedia
    window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as any

    vi.doMock('element-plus/theme-chalk/dark/css-vars.css', () => ({}))
    vi.doMock('../variables.css', () => ({}))

    const { useTheme } = await import('../index')
    const { theme } = useTheme()
    expect(theme.value).toBe('dark')

    window.matchMedia = originalMatchMedia
  })
})
