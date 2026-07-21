import type { ResourcePartitionId } from '@/museum/core/types'
import type { LibraryScene } from '@/museum/runtime/scene/LibraryScene'
import type { Router } from 'vue-router'

/**
 * 12-room → route mapping.
 * Matches ClawLibrary resource partition IDs to OpenClaw-Admin route paths.
 * Routes are absolute paths under the authenticated layout.
 */
export const ROOM_ROUTE_MAP: Record<ResourcePartitionId, string> = {
  agent: '/agents',
  task_queues: '/agents',       // task tab within agents page
  gateway: '/chat',
  memory: '/memory',
  skills: '/skills',
  log: '/system',
  document: '/files',
  schedule: '/cron',
  alarm: '/system',             // alarm section within system page
  mcp: '/skills',               // MCP config within skills page
  images: '/settings',
  break_room: '/break-room'     // easter egg route
}

/**
 * Resource label mapping for display purposes.
 */
export const ROOM_LABEL_MAP: Record<ResourcePartitionId, string> = {
  agent: 'Agent',
  task_queues: 'Task Queues',
  gateway: 'Gateway',
  memory: 'Memory',
  skills: 'Skills',
  log: 'Log',
  document: 'Document',
  schedule: 'Schedule',
  alarm: 'Alarm',
  mcp: 'MCP',
  images: 'Images',
  break_room: 'Break Room'
}

export interface RouterSyncOptions {
  /** Vue Router instance */
  router: Router
  /** LibraryScene instance (available after create phase) */
  scene: LibraryScene
}

/**
 * Bind LibraryScene room-select events to Vue Router navigation.
 *
 * When user clicks a room in the museum, this adapter:
 * 1. Listens for 'select-resource' event from Phaser scene
 * 2. Maps resourceId → route path
 * 3. Calls router.push() to navigate
 */
export function bindRoomRouterSync(options: RouterSyncOptions): () => void {
  const { router, scene } = options

  const handler = (resourceId: ResourcePartitionId) => {
    const route = ROOM_ROUTE_MAP[resourceId]
    if (route && router.currentRoute.value.path !== route) {
      router.push(route)
    }
  }

  scene.events.on('select-resource', handler)

  // Return unbind function
  return () => {
    scene.events.off('select-resource', handler)
  }
}

/**
 * Navigate to the route mapped to a resource partition ID.
 * Convenience function for programmatic navigation.
 */
export function navigateToRoom(router: Router, resourceId: ResourcePartitionId): void {
  const route = ROOM_ROUTE_MAP[resourceId]
  if (route) {
    router.push(route)
  }
}
