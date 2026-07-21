/**
 * Agent 路由器 — 基于规则的任务智能分发引擎
 *
 * 根据任务类型/内容，自动匹配最佳 Agent 系统进行处理。
 */

import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { GatewayId } from '@/stores/hermes/connection'

export interface RouterRule {
  id: string
  name: string
  description?: string
  priority: number
  /** 匹配条件: 任务描述/标题包含的关键词 */
  keywords: string[]
  /** 目标 Agent */
  target: GatewayId
  enabled: boolean
}

function defaultRules(): RouterRule[] {
  return [
    {
      id: 'urgent',
      name: '紧急任务',
      description: '高优先级紧急任务 → myself-agent 快速执行',
      priority: 200,
      keywords: ['紧急', 'urgent', '立刻', '马上', '尽快', 'asap'],
      target: 'myself-agent',
      enabled: true,
    },
    {
      id: 'chat',
      name: '聊天交互',
      description: '对话/聊天类任务 → OpenClaw',
      priority: 100,
      keywords: ['聊天', '对话', 'chat', 'conversation'],
      target: 'openclaw',
      enabled: true,
    },
    {
      id: 'coding',
      name: '编码开发',
      description: '编码/自动化/开发任务 → myself-agent',
      priority: 90,
      keywords: ['代码', '开发', '编码', '自动化', 'code', 'build', 'deploy', '测试', 'test', '重构', 'refactor'],
      target: 'myself-agent',
      enabled: true,
    },
    {
      id: 'research',
      name: '研究与搜索',
      description: '研究/信息收集类任务 → Hermes',
      priority: 85,
      keywords: ['研究', '搜索', '查找', '分析', 'research', 'search', 'analyze', '调查'],
      target: 'hermes',
      enabled: true,
    },
    {
      id: 'data',
      name: '数据处理',
      description: '数据分析/ETL任务 → myself-agent',
      priority: 80,
      keywords: ['数据', '数据库', 'ETL', 'data', '报表', 'report', '统计', 'statistics'],
      target: 'myself-agent',
      enabled: true,
    },
    {
      id: 'fallback',
      name: '默认兜底',
      description: '无法匹配的任务 → OpenClaw 通用处理',
      priority: 0,
      keywords: [],
      target: 'openclaw',
      enabled: true,
    },
  ]
}

export const useAgentRouterStore = defineStore('agent-router', () => {
  const rules = ref<RouterRule[]>(defaultRules())
  const lastRouted = ref<{ task: string; target: GatewayId; rule: string } | null>(null)

  const enabledRules = computed(() =>
    rules.value.filter((r) => r.enabled).sort((a, b) => b.priority - a.priority),
  )

  /**
   * 根据任务描述路由到最佳 Agent
   */
  function route(task: string): { target: GatewayId; rule: RouterRule } {
    const lower = task.toLowerCase()
    for (const rule of enabledRules.value) {
      if (rule.keywords.length === 0) {
        // 兜底规则
        lastRouted.value = { task, target: rule.target, rule: rule.name }
        return { target: rule.target, rule }
      }
      for (const kw of rule.keywords) {
        if (lower.includes(kw.toLowerCase())) {
          lastRouted.value = { task, target: rule.target, rule: rule.name }
          return { target: rule.target, rule }
        }
      }
    }
    // 永远不应到达（因为有兜底规则）
    lastRouted.value = { task, target: 'openclaw', rule: 'fallback' }
    return { target: 'openclaw', rule: rules.value.find((r) => r.id === 'fallback')! }
  }

  function addRule(rule: RouterRule) {
    rules.value = [...rules.value, rule]
  }

  function updateRule(id: string, patch: Partial<RouterRule>) {
    rules.value = rules.value.map((r) => (r.id === id ? { ...r, ...patch } : r))
  }

  function removeRule(id: string) {
    rules.value = rules.value.filter((r) => r.id !== id)
  }

  function resetToDefaults() {
    rules.value = defaultRules()
    lastRouted.value = null
  }

  return {
    rules,
    lastRouted,
    enabledRules,
    route,
    addRule,
    updateRule,
    removeRule,
    resetToDefaults,
  }
})
