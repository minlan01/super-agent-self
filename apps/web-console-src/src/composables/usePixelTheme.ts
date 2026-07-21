import { computed } from 'vue'
import { darkTheme } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'

/**
 * Generate Naive UI themeOverrides based on pixel-tokens.css variables.
 * Covers common + Card/Menu/Button/Input/Tag/Table/Dialog.
 * The CSS variables are read from :root (set by <html data-theme="xxx">).
 */

function getCssVar(name: string): string {
  if (typeof document === 'undefined') return ''
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

export function usePixelTheme() {
  const themeOverrides = computed<GlobalThemeOverrides>(() => {
    const accent = getCssVar('--accent') || '#45d1b3'
    const ink = getCssVar('--ink') || 'rgba(236, 247, 243, 0.92)'
    const ink2 = getCssVar('--ink-secondary') || 'rgba(203, 229, 221, 0.82)'
    const muted = getCssVar('--muted') || 'rgba(152, 181, 172, 0.9)'
    const dim = getCssVar('--dim') || 'rgba(115, 144, 136, 0.7)'
    const line = getCssVar('--line') || 'rgba(171, 218, 201, 0.14)'
    const lineStrong = getCssVar('--line-strong') || 'rgba(171, 218, 201, 0.28)'
    const bgDeepest = getCssVar('--bg-deepest') || '#080d11'
    const bgMid = getCssVar('--bg-mid') || '#0e1418'
    const bgUpper = getCssVar('--bg-upper') || '#12171b'
    const bgSurface = getCssVar('--bg-surface') || '#16191d'

    return {
      common: {
        primaryColor: accent,
        primaryColorHover: accent,
        primaryColorPressed: accent,
        primaryColorSuppl: accent,
        bodyColor: bgDeepest,
        cardColor: bgMid,
        modalColor: bgUpper,
        popoverColor: bgUpper,
        dividerColor: line,
        borderColor: line,
        fontFamily: `"VT323", "Courier New", monospace`,
        fontSize: '14px',
        textColor1: ink,
        textColor2: ink2,
        textColor3: muted,
        borderRadius: '0px',
        lineHeight: '1.5',
        heightSmall: '28px',
        heightMedium: '34px',
        heightLarge: '40px',
      },
      Card: {
        borderRadius: '0px',
        borderColor: line,
        color: bgMid,
        titleTextColor: ink,
        textColor: ink2,
        boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.03), 0 2px 10px rgba(0,0,0,0.18)',
        paddingSmall: '12px',
        paddingMedium: '16px',
        paddingLarge: '20px',
      },
      Menu: {
        itemColor: 'transparent',
        itemColorHover: 'rgba(69, 209, 179, 0.08)',
        itemColorActive: 'rgba(69, 209, 179, 0.15)',
        itemTextColor: ink2,
        itemTextColorHover: ink,
        itemTextColorActive: accent,
        itemTextColorChildActive: accent,
        itemIconColor: muted,
        itemIconColorHover: accent,
        itemIconColorActive: accent,
        dividerColor: line,
      },
      Button: {
        borderRadiusSmall: '0px',
        borderRadiusMedium: '0px',
        borderRadiusLarge: '0px',
        border: `1px solid ${lineStrong}`,
        borderHover: `1px solid ${accent}`,
        borderPressed: `1px solid ${accent}`,
        borderDisabled: `1px solid ${line}`,
        color: bgUpper,
        colorHover: bgSurface,
        colorPressed: bgMid,
        colorDisabled: bgMid,
        textColor: ink,
        textColorHover: accent,
        textColorPressed: accent,
        textColorDisabled: dim,
      },
      Input: {
        borderRadius: '0px',
        border: `1px solid ${line}`,
        borderHover: `1px solid ${lineStrong}`,
        borderFocus: `1px solid ${accent}`,
        color: bgMid,
        colorFocus: bgUpper,
        textColor: ink,
        placeholderColor: dim,
        lineHeight: '1.5',
        heightSmall: '28px',
        heightMedium: '34px',
        heightLarge: '40px',
      },
      Tag: {
        borderRadius: '4px',
        border: `1px solid ${line}`,
        color: 'rgba(10, 24, 22, 0.64)',
        textColor: ink2,
      },
      Table: {
        borderRadius: '0px',
        borderColor: line,
        thColor: bgMid,
        thTextColor: accent,
        tdColor: bgUpper,
        tdTextColor: ink2,
        tdColorHover: 'rgba(69, 209, 179, 0.06)',
        thPaddingSmall: '8px 12px',
        thPaddingMedium: '10px 14px',
        tdPaddingSmall: '8px 12px',
        tdPaddingMedium: '10px 14px',
      },
      Dialog: {
        borderRadius: '0px',
        border: `1px solid ${lineStrong}`,
        color: bgUpper,
        titleTextColor: ink,
        textColor: ink2,
        closeColorHover: accent,
        boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.05), 0 8px 32px rgba(0,0,0,0.4)',
      },
      Layout: {
        color: 'transparent',
        siderColor: bgMid,
        siderBorderColor: line,
        headerColor: bgUpper,
        headerBorderColor: line,
        footerColor: bgMid,
      },
      Tabs: {
        tabTextColor: ink2,
        tabTextColorHover: ink,
        tabTextColorActive: accent,
        tabColor: 'transparent',
        barColor: accent,
        paneTextColor: ink2,
      },
      Select: {
        peers: {
          InternalSelection: {
            borderRadius: '0px',
            border: `1px solid ${line}`,
            borderHover: `1px solid ${lineStrong}`,
            borderFocus: `1px solid ${accent}`,
            color: bgMid,
            textColor: ink2,
          },
          InternalSelectMenu: {
            color: bgUpper,
          },
        },
      },
      Dropdown: {
        color: bgUpper,
        optionColorHover: 'rgba(69, 209, 179, 0.08)',
        optionTextColor: ink2,
        optionTextColorHover: ink,
        dividerColor: line,
      },
      Popover: {
        color: bgUpper,
        textColor: ink2,
        border: `1px solid ${lineStrong}`,
        borderRadius: '0px',
      },
      Notification: {
        color: bgUpper,
        textColor: ink,
        border: `1px solid ${lineStrong}`,
        borderRadius: '0px',
        titleTextColor: ink,
      },
      Switch: {
        railColorActive: accent,
      },
      Slider: {
        fillColor: accent,
        fillColorHover: accent,
      },
      Progress: {
        fillColor: accent,
        railColor: 'rgba(0, 0, 0, 0.4)',
      },
    }
  })

  /** Combined Naive UI theme (dark base + pixel overrides) */
  const naiveTheme = computed(() => {
    const overrides = themeOverrides.value
    return {
      ...darkTheme,
      common: { ...darkTheme?.common, ...overrides.common },
      ...Object.fromEntries(
        Object.entries(overrides).filter(([key]) => key !== 'common')
      ),
    }
  })

  return {
    themeOverrides,
    naiveTheme,
  }
}
