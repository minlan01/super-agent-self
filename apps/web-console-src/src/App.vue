<script setup lang="ts">
import { computed, watch } from "vue";
import { useRoute } from "vue-router";
import {
  NConfigProvider,
  NMessageProvider,
  NDialogProvider,
  NNotificationProvider,
  darkTheme,
  zhCN,
  enUS,
  dateZhCN,
  dateEnUS,
} from "naive-ui";
import { useI18n } from "vue-i18n";
import { useTheme } from "@/composables/useTheme";
import { usePixelTheme } from "@/composables/usePixelTheme";
import { useLocaleStore } from "@/stores/locale";

const route = useRoute();
const localeStore = useLocaleStore();
const { t } = useI18n();
const { pixelTheme } = useTheme();
const { themeOverrides } = usePixelTheme();

const naiveLocale = computed(() =>
  localeStore.locale === "zh-CN" ? zhCN : enUS,
);
const naiveDateLocale = computed(() =>
  localeStore.locale === "zh-CN" ? dateZhCN : dateEnUS,
);

// Sync pixel theme to <html> data-theme for CSS variable switching
watch(pixelTheme, (val) => {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", val);
}, { immediate: true });

watch(
  () =>
    [route.meta.titleKey as string | undefined, localeStore.locale] as const,
  ([titleKey]) => {
    if (typeof document === "undefined") return;
    if (!titleKey) {
      document.title = "Agent Command Center";
      return;
    }
    const title = t(titleKey);
    document.title = `${title} - Agent Command Center`;
  },
  { immediate: true },
);
</script>

<template>
  <NConfigProvider
    :theme="darkTheme"
    :theme-overrides="themeOverrides"
    :locale="naiveLocale"
    :date-locale="naiveDateLocale"
  >
    <NNotificationProvider>
      <NMessageProvider>
        <NDialogProvider>
          <RouterView />
        </NDialogProvider>
      </NMessageProvider>
    </NNotificationProvider>
  </NConfigProvider>
</template>
