<template>
  <el-card shadow="hover">
    <template #header>{{ label }}</template>
    <div class="stat-value" :style="color ? { color } : undefined">
      <slot>{{ value }}</slot>
    </div>
  </el-card>
</template>

<script setup lang="ts">
defineProps<{
  label: string
  value?: string | number
  color?: string
}>()
</script>

<style scoped>
.stat-value {
  font-size: 32px;
  font-weight: bold;
  text-align: center;
  padding: 10px 0;
  color: var(--theme-stat-value-color);
}
</style>
