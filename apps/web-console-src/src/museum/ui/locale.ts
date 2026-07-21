export type UiLocale = 'en' | 'zh';

export const RESOURCE_LABELS: Record<string, Record<UiLocale, string>> = {
  document: { en: 'Documents Archive', zh: '文档归档' },
  images: { en: 'Image Atelier', zh: '图像工坊' },
  memory: { en: 'Memory Vault', zh: '记忆库' },
  skills: { en: 'Skill Forge', zh: '技能锻炉' },
  gateway: { en: 'Interface Gateway', zh: '接口网关' },
  log: { en: 'Log Deck', zh: '日志台' },
  mcp: { en: 'Code Lab', zh: '代码实验室' },
  schedule: { en: 'Scheduler Deck', zh: '调度台' },
  alarm: { en: 'Alert Deck', zh: '报警台' },
  agent: { en: 'Run Dock', zh: '运行监控' },
  task_queues: { en: 'Queue Hub', zh: '队列中枢' },
  break_room: { en: 'Breakroom', zh: '休息室' }
};

export const UI_TEXT = {
  title: { en: 'ClawLibrary', zh: '龙虾图书馆' },
  recentActivity: { en: 'Recent Activity', zh: '最近活动' },
  noActivity: { en: 'No recent activity yet.', zh: '暂时还没有最近活动。' },
  archiveLive: { en: 'ARCHIVE LIVE', zh: '实时归档' },
  quickRooms: { en: 'Quick room routing', zh: '快速房间路由' },
  statsAssets: { en: 'assets', zh: '资产' },
  statsLive: { en: 'live', zh: '在线' },
  statsEvents: { en: 'events 24h', zh: '24h 事件' },
  waiting: { en: 'waiting', zh: '等待中' },
  hideInfo: { en: 'Hide Info', zh: '隐藏信息' },
  showInfo: { en: 'Show Info', zh: '显示信息' },
  shortcuts: { en: 'Shortcuts', zh: '快捷键' },
  search: { en: 'Search', zh: '搜索' },
  copyContext: { en: 'Copy Context', zh: '复制上下文' },
  close: { en: 'Close', zh: '关闭' },
  grid: { en: 'Grid', zh: '网格' },
  list: { en: 'List', zh: '列表' },
  allKinds: { en: 'All Kinds', zh: '全部分类' },
  recommended: { en: 'Recommended', zh: '推荐' },
  newest: { en: 'Newest', zh: '最新' },
  oldest: { en: 'Oldest', zh: '最早' },
  largest: { en: 'Largest', zh: '最大' },
  smallest: { en: 'Smallest', zh: '最小' },
  theme: { en: 'Theme', zh: '主题' },
  debug: { en: 'Debug', zh: '调试' },
  clawSkin: { en: 'Claw', zh: '爪形' },
  preview: { en: 'Preview', zh: '预览' },
  loadingPreview: { en: 'Loading preview…', zh: '预览加载中…' },
  open: { en: 'Open', zh: '打开' },
  openFolder: { en: 'Open Folder', zh: '打开目录' },
  copyPath: { en: 'Copy Path', zh: '复制路径' },
  copyExcerpt: { en: 'Copy Excerpt', zh: '复制摘要' },
  openSource: { en: 'Open Source', zh: '打开来源' },
  copySource: { en: 'Copy Source', zh: '复制来源' },
  openTopItem: { en: 'Open Top Item', zh: '打开首项' },
  copyDetail: { en: 'Copy Detail', zh: '复制详情' },
  topItem: { en: 'Top Item', zh: '首项' },
  recentEvents: { en: 'Recent Events', zh: '最近事件' },
  status: { en: 'Status', zh: '状态' },
  source: { en: 'Source', zh: '来源' },
  signal: { en: 'Signal', zh: '信号' },
  focus: { en: 'Focus', zh: '焦点' },
  pointer: { en: 'Pointer', zh: '指针' },
  client: { en: 'Client', zh: '屏幕' },
  scene: { en: 'Scene', zh: '场景' },
  lastClick: { en: 'Last Click', zh: '上次点击' },
  clickClient: { en: 'Click Client', zh: '点击屏幕' },
  stageInside: { en: 'Inside Stage', zh: '在场景内' },
  stageOutside: { en: 'Outside Stage', zh: '场景外' },
  active: { en: 'Active', zh: '活跃' },
  idle: { en: 'Idle', zh: '空闲' },
  alert: { en: 'Alert', zh: '告警' },
  offline: { en: 'Offline', zh: '离线' }
} as const;

export function resourceLabel(id: string, locale: UiLocale): string {
  return RESOURCE_LABELS[id]?.[locale] ?? id;
}

export function uiText<K extends keyof typeof UI_TEXT>(key: K, locale: UiLocale): string {
  return UI_TEXT[key][locale];
}
