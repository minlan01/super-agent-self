<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NBreadcrumb, NBreadcrumbItem, NButton, NSpace, NTooltip, NIcon } from 'naive-ui'
import { SunnyOutline, MoonOutline, LogOutOutline, LanguageOutline, ExpandOutline, ContractOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { useTheme } from '@/composables/useTheme'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import { useWebSocketStore } from '@/stores/websocket'
import { useWideModeStore } from '@/stores/wideMode'
import ConnectionStatus from '@/components/common/ConnectionStatus.vue'
import GatewaySwitcher from '@/components/common/GatewaySwitcher.vue'

const route = useRoute()
const router = useRouter()
const { isDark, toggle } = useTheme()
const authStore = useAuthStore()
const localeStore = useLocaleStore()
const wsStore = useWebSocketStore()
const wideModeStore = useWideModeStore()
const { t } = useI18n()

const isMobile = ref(window.innerWidth <= 768)

function onResize() {
  isMobile.value = window.innerWidth <= 768
}

onMounted(() => window.addEventListener('resize', onResize))
onUnmounted(() => window.removeEventListener('resize', onResize))

const breadcrumbs = computed(() => {
  const items: { label: string; name?: string }[] = [{ label: t('common.home'), name: 'Dashboard' }]
  if (route.name !== 'Dashboard') {
    const titleKey = route.meta.titleKey as string | undefined
    const fallbackTitle = route.meta.title as string | undefined
    items.push({ label: titleKey ? t(titleKey) : (fallbackTitle || '') })
  }
  return items
})

const languageToggleTarget = computed(() => (localeStore.locale === 'zh-CN' ? t('common.languageEn') : t('common.languageZh')))

async function handleLogout() {
  wsStore.disconnect()
  await authStore.logout()
  router.push({ name: 'Login' })
}
</script>

<template>
  <div class="pixel-header header-root">
    <!-- Breadcrumb: full on desktop, current page only on mobile -->
    <NBreadcrumb v-if="!isMobile" class="pixel-breadcrumb">
      <NBreadcrumbItem
        v-for="(item, index) in breadcrumbs"
        :key="index"
        @click="item.name ? router.push({ name: item.name }) : undefined"
      >
        {{ item.label }}
      </NBreadcrumbItem>
    </NBreadcrumb>
    <span v-else class="pixel-breadcrumb mobile-page-title">
      {{ breadcrumbs.length > 1 ? breadcrumbs[breadcrumbs.length - 1]?.label : breadcrumbs[0]?.label }}
    </span>

    <NSpace :size="isMobile ? 4 : 8" align="center" :wrap="false">
      <ConnectionStatus v-if="!isMobile" />
      <GatewaySwitcher />

      <NTooltip>
        <template #trigger>
          <NButton class="pixel-header-btn" :aria-label="isDark ? t('common.switchToLight') : t('common.switchToDark')" @click="toggle">
            <template #icon>
              <NIcon :size="16" :component="isDark ? SunnyOutline : MoonOutline" />
            </template>
          </NButton>
        </template>
        {{ isDark ? t('common.switchToLight') : t('common.switchToDark') }}
      </NTooltip>

      <NTooltip v-if="!isMobile">
        <template #trigger>
          <NButton class="pixel-header-btn" :aria-label="wideModeStore.isWideMode ? t('common.switchToNormalWidth') : t('common.switchToWideMode')" @click="wideModeStore.toggle">
            <template #icon>
              <NIcon :size="16" :component="wideModeStore.isWideMode ? ContractOutline : ExpandOutline" />
            </template>
          </NButton>
        </template>
        {{ wideModeStore.isWideMode ? t('common.switchToNormalWidth') : t('common.switchToWideMode') }}
      </NTooltip>

      <NTooltip>
        <template #trigger>
          <NButton class="pixel-header-btn" :aria-label="t('common.toggleLanguage', { target: languageToggleTarget })" @click="localeStore.toggle">
            <template #icon>
              <NIcon :size="16" :component="LanguageOutline" />
            </template>
          </NButton>
        </template>
        {{ t('common.toggleLanguage', { target: languageToggleTarget }) }}
      </NTooltip>

      <NTooltip>
        <template #trigger>
          <NButton class="pixel-header-btn" :aria-label="t('common.logout')" @click="handleLogout">
            <template #icon>
              <NIcon :size="16" :component="LogOutOutline" />
            </template>
          </NButton>
        </template>
        {{ t('common.logout') }}
      </NTooltip>
    </NSpace>
  </div>
</template>

<style scoped>
.header-root {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-width: 0;
}

.mobile-page-title {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 180px;
}

@media (max-width: 768px) {
  .mobile-page-title {
    max-width: 120px;
  }
}
</style>
