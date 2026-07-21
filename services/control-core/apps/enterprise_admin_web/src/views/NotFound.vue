<template>
  <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 400px">
    <h1 style="font-size: 72px; color: var(--theme-text-secondary); margin: 0">{{ t('notFound.title') }}</h1>
    <p style="color: var(--theme-text-secondary); font-size: 18px; margin-top: 8px">{{ t('notFound.description') }}</p>
    <el-button type="primary" @click="$router.push('/')" style="margin-top: 20px">{{ t('notFound.backToDashboard') }}</el-button>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>
