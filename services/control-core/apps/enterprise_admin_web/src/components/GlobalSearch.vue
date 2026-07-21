<template>
  <div class="global-search">
    <el-popover
      v-model:visible="popoverVisible"
      :width="420"
      placement="bottom-start"
      trigger="focus"
      :show-arrow="false"
      :offset="4"
      popper-class="search-popover"
    >
      <template #reference>
        <el-input
          v-model="query"
          :placeholder="t('search.placeholder')"
          :prefix-icon="Search"
          clearable
          size="default"
          class="search-input"
          @input="handleInput"
          @clear="handleClear"
          @keydown.down.prevent="navigateDown"
          @keydown.up.prevent="navigateUp"
          @keydown.enter="selectCurrent"
          @keydown.escape="popoverVisible = false"
        />
      </template>

      <div v-if="loading" class="search-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>{{ t('search.searching') }}</span>
      </div>

      <div v-else-if="hasResults" class="search-results">
        <template v-for="group in resultGroups" :key="group.key">
          <div v-if="group.items.length > 0" class="search-group">
            <div class="search-group-title">{{ group.label }}</div>
            <div
              v-for="(item, idx) in group.items"
              :key="item.id"
              class="search-item"
              :class="{ 'is-active': activeIndex === getFlatIndex(group.key, idx) }"
              @click="goToResult(item)"
              @mouseenter="activeIndex = getFlatIndex(group.key, idx)"
            >
              <el-icon class="search-item-icon"><component :is="group.icon" /></el-icon>
              <div class="search-item-content">
                <div class="search-item-title">{{ item.title }}</div>
                <div class="search-item-meta">{{ item.matched_field }}</div>
              </div>
            </div>
          </div>
        </template>
      </div>

      <div v-else-if="query && query.length >= 2 && !loading" class="search-empty">
        {{ t('search.noResults') }}
      </div>

      <div v-else-if="query && query.length < 2" class="search-empty">
        {{ t('search.placeholder') }}
      </div>
    </el-popover>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Search, Loading, List, Collection, MagicStick, ChatLineSquare } from '@element-plus/icons-vue'
import { searchApi } from '../api/index'
import type { SearchResults, SearchHit } from '../types'

type SearchResult = SearchHit

const { t } = useI18n()
const router = useRouter()

const query = ref('')
const loading = ref(false)
const popoverVisible = ref(false)
const activeIndex = ref(-1)
const results = ref<SearchResults>({
  tasks: [],
  memories: [],
  skills: [],
  conversations: [],
})

let debounceTimer: ReturnType<typeof setTimeout> | null = null

const resultGroups = computed(() => [
  {
    key: 'tasks' as const,
    label: t('search.tasks'),
    icon: List,
    items: results.value.tasks,
    routePrefix: '/tasks',
  },
  {
    key: 'memories' as const,
    label: t('search.memories'),
    icon: Collection,
    items: results.value.memories,
    routePrefix: '/memory',
  },
  {
    key: 'skills' as const,
    label: t('search.skills'),
    icon: MagicStick,
    items: results.value.skills,
    routePrefix: '/skills',
  },
  {
    key: 'conversations' as const,
    label: t('search.conversations'),
    icon: ChatLineSquare,
    items: results.value.conversations,
    routePrefix: '/conversations',
  },
])

const hasResults = computed(() => {
  return (
    results.value.tasks.length > 0 ||
    results.value.memories.length > 0 ||
    results.value.skills.length > 0 ||
    results.value.conversations.length > 0
  )
})

const totalFlatItems = computed(() => {
  return resultGroups.value.reduce((sum, g) => sum + g.items.length, 0)
})

function getFlatIndex(groupKey: string, idx: number): number {
  let flatIdx = 0
  for (const group of resultGroups.value) {
    if (group.key === groupKey) {
      return flatIdx + idx
    }
    flatIdx += group.items.length
  }
  return idx
}

function getFlatItem(index: number): { group: (typeof resultGroups.value)[number]; item: SearchResult } | null {
  let offset = 0
  for (const group of resultGroups.value) {
    if (index < offset + group.items.length) {
      return { group, item: group.items[index - offset] }
    }
    offset += group.items.length
  }
  return null
}

function handleInput() {
  if (debounceTimer) {
    clearTimeout(debounceTimer)
  }
  if (query.value.length < 2) {
    results.value = { tasks: [], memories: [], skills: [], conversations: [] }
    loading.value = false
    return
  }
  loading.value = true
  activeIndex.value = -1
  debounceTimer = setTimeout(async () => {
    await doSearch()
  }, 300)
}

async function doSearch() {
  try {
    const res = await searchApi.query({ q: query.value, limit: 5 })
    results.value = res.results || { tasks: [], memories: [], skills: [], conversations: [] }
  } catch {
    results.value = { tasks: [], memories: [], skills: [], conversations: [] }
  } finally {
    loading.value = false
  }
}

function handleClear() {
  query.value = ''
  results.value = { tasks: [], memories: [], skills: [], conversations: [] }
  activeIndex.value = -1
}

function navigateDown() {
  if (totalFlatItems.value === 0) return
  activeIndex.value = (activeIndex.value + 1) % totalFlatItems.value
}

function navigateUp() {
  if (totalFlatItems.value === 0) return
  activeIndex.value = activeIndex.value <= 0 ? totalFlatItems.value - 1 : activeIndex.value - 1
}

function selectCurrent() {
  const entry = getFlatItem(activeIndex.value)
  if (entry) {
    goToResult(entry.item)
  }
}

function goToResult(item: SearchResult) {
  // Determine route from matched field context
  const group = resultGroups.value.find((g) =>
    g.items.some((i) => i.id === item.id)
  )
  if (!group) return

  let route = group.routePrefix
  // For entities with detail pages
  if (['tasks', 'skills'].includes(group.key)) {
    route = `${group.routePrefix}/${item.id}`
  }

  popoverVisible.value = false
  router.push(route)
}
</script>

<style scoped>
.global-search {
  display: inline-flex;
  align-items: center;
}

.search-input {
  width: 260px;
}

.search-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  color: var(--theme-color-info);
  font-size: 13px;
}

.search-results {
  max-height: 400px;
  overflow-y: auto;
}

.search-group-title {
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 600;
  color: var(--theme-color-info);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.search-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
}

.search-item:hover,
.search-item.is-active {
  background: #f5f7fa;
}

.search-item-icon {
  color: var(--theme-color-info);
  font-size: 16px;
  flex-shrink: 0;
}

.search-item-content {
  flex: 1;
  min-width: 0;
}

.search-item-title {
  font-size: 13px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-item-meta {
  font-size: 11px;
  color: #c0c4cc;
  margin-top: 2px;
}

.search-empty {
  padding: 16px;
  text-align: center;
  color: var(--theme-color-info);
  font-size: 13px;
}
</style>
