<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NLayout, NLayoutSider, NLayoutHeader, NLayoutContent, NDrawer, NDrawerContent } from 'naive-ui'
import AppHeader from '@/components/layout/AppHeader.vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import { useWebSocketStore } from '@/stores/websocket'
import { useHermesConnectionStore } from '@/stores/hermes/connection'

const collapsed = ref(false)
const mobileDrawerVisible = ref(false)
const wsStore = useWebSocketStore()
const connStore = useHermesConnectionStore()
const route = useRoute()
const router = useRouter()

const MOBILE_BREAKPOINT = 768

const isMobile = ref(window.innerWidth <= MOBILE_BREAKPOINT)

function onResize() {
  const wasMobile = isMobile.value
  isMobile.value = window.innerWidth <= MOBILE_BREAKPOINT
  // Auto-collapse sidebar when entering mobile
  if (isMobile.value && !wasMobile) {
    collapsed.value = true
  }
  // Auto-expand sidebar when leaving mobile
  if (!isMobile.value && wasMobile) {
    collapsed.value = false
    mobileDrawerVisible.value = false
  }
}

const isOpenClaw = computed(() => connStore.currentGateway === 'openclaw')

onMounted(() => {
  window.addEventListener('resize', onResize)
  onResize()

  if (isOpenClaw.value) {
    wsStore.connect()
  } else {
    connStore.connect()
  }

  const currentGateway = isOpenClaw.value ? 'openclaw' : 'hermes'
  const routeGateway = route.meta?.gateway as string | undefined
  if (routeGateway && routeGateway !== currentGateway) {
    router.replace(isOpenClaw.value ? '/' : '/hermes/chat')
  }
})

watch(isOpenClaw, (val) => {
  if (val) {
    wsStore.connect()
    connStore.disconnect()
  } else {
    wsStore.disconnect()
    connStore.connect()
  }

  const currentGateway = val ? 'openclaw' : 'hermes'
  const routeGateway = route.meta?.gateway as string | undefined
  if (routeGateway && routeGateway !== currentGateway) {
    router.push(val ? '/' : '/hermes/chat')
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  wsStore.disconnect()
})

function toggleMobileDrawer() {
  mobileDrawerVisible.value = !mobileDrawerVisible.value
}

function closeMobileDrawer() {
  mobileDrawerVisible.value = false
}
</script>

<template>
  <NLayout has-sider position="absolute" class="app-layout-root">
    <!-- Desktop sidebar -->
    <NLayoutSider
      v-if="!isMobile"
      class="app-layout-sider pixel-sider"
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="240"
      :collapsed="collapsed"
      show-trigger
      :native-scrollbar="false"
      style="height: 100vh;"
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <AppSidebar :collapsed="collapsed" />
    </NLayoutSider>

    <!-- Mobile drawer sidebar -->
    <NDrawer
      v-if="isMobile"
      :show="mobileDrawerVisible"
      placement="left"
      :width="240"
      :auto-focus="false"
      @update:show="(v: boolean) => mobileDrawerVisible = v"
    >
      <NDrawerContent :native-scrollbar="false" body-content-style="padding: 0;" class="pixel-sider-drawer">
        <AppSidebar :collapsed="false" @select="closeMobileDrawer" />
      </NDrawerContent>
    </NDrawer>

    <NLayout class="app-layout-main">
      <NLayoutHeader bordered class="app-layout-header">
        <!-- Mobile hamburger button -->
        <button v-if="isMobile" class="mobile-menu-btn" @click="toggleMobileDrawer">
          <span class="hamburger-icon">☰</span>
        </button>
        <AppHeader />
      </NLayoutHeader>

      <NLayoutContent
        class="app-layout-content"
        :native-scrollbar="false"
        :content-style="isMobile ? 'padding: 16px;' : 'padding: 24px;'"
      >
        <div class="page-container">
          <RouterView v-slot="{ Component }">
            <transition name="fade" mode="out-in">
              <component :is="Component" />
            </transition>
          </RouterView>
        </div>
      </NLayoutContent>
    </NLayout>
  </NLayout>
</template>

<style scoped>
.app-layout-root {
  inset: 0;
  height: 100vh;
  overflow: hidden;
}

.app-layout-main {
  height: 100vh;
  overflow: hidden;
}

.app-layout-header {
  height: var(--header-height);
  padding: 0 24px;
  display: flex;
  align-items: center;
  position: sticky;
  top: 0;
  z-index: 12;
  background: var(--bg-card);
  gap: 8px;
}

.app-layout-content {
  height: calc(100vh - var(--header-height));
}

:deep(.app-layout-content .n-layout-scroll-container) {
  height: 100%;
}

/* Mobile hamburger button */
.mobile-menu-btn {
  width: 34px;
  height: 34px;
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--ease-fast);
}

.mobile-menu-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--panel-strong);
  box-shadow: 0 0 8px var(--accent-glow);
}

.hamburger-icon {
  font-size: 18px;
  line-height: 1;
  font-family: var(--font-sans);
}

/* Mobile drawer styles */
.pixel-sider-drawer {
  background: linear-gradient(180deg, var(--panel-strong), var(--panel)) !important;
}

:deep(.pixel-sider-drawer .n-drawer-body-content-wrapper) {
  padding: 0 !important;
}

@media (max-width: 768px) {
  .app-layout-header {
    padding: 0 12px;
  }
}
</style>
