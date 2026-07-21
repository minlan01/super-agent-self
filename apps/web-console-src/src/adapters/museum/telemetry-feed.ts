import type { OpenClawSnapshot, ActiveAgent, ActiveExecProcess } from '@/museum/core/types'
import type { ResourcePartitionId } from '@/museum/core/types'
import type { LibraryScene } from '@/museum/runtime/scene/LibraryScene'

export interface TelemetryFeedOptions {
  /** LibraryScene instance */
  scene: LibraryScene
}

/**
 * Push telemetry data into the Phaser museum scene.
 *
 * Takes an OpenClawSnapshot (fetched from backend) and pushes it into
 * LibraryScene so the museum reflects live agent/process/resource state.
 *
 * Usage:
 *   const feed = createTelemetryFeed({ scene })
 *   feed.push(snapshot)  // call on each poll cycle
 *   feed.dispose()       // cleanup
 */
export function createTelemetryFeed(options: TelemetryFeedOptions) {
  const { scene } = options

  let prevActiveAgentIds = new Set<string>()
  let prevActiveProcessIds = new Set<string>()

  function push(snapshot: OpenClawSnapshot): void {
    // 1. Push snapshot to scene (updates resource telemetry, focus, context bar)
    scene.applyTelemetrySnapshot(snapshot)

    // 2. Diff active agents: spawn new, despawn gone
    const currentAgents: ActiveAgent[] = snapshot.activeAgents ?? []
    const currentAgentIds = new Set(currentAgents.map((a) => a.id))

    for (const agent of currentAgents) {
      if (!prevActiveAgentIds.has(agent.id)) {
        scene.spawnAgentActor(agent.id, agent.label, 'subagent')
      }
    }
    for (const prevId of prevActiveAgentIds) {
      if (!currentAgentIds.has(prevId)) {
        scene.despawnAgentActor(prevId)
      }
    }
    prevActiveAgentIds = currentAgentIds

    // 3. Diff active processes: spawn new, despawn gone
    const currentProcesses: ActiveExecProcess[] = snapshot.activeProcesses ?? []
    const currentProcessIds = new Set(currentProcesses.map((p) => p.id))

    for (const proc of currentProcesses) {
      if (!prevActiveProcessIds.has(proc.id)) {
        scene.spawnAgentActor(`proc:${proc.id}`, proc.label, 'exec-process')
      }
    }
    for (const prevId of prevActiveProcessIds) {
      if (!currentProcessIds.has(prevId)) {
        scene.despawnAgentActor(`proc:${prevId}`)
      }
    }
    prevActiveProcessIds = currentProcessIds
  }

  function applyFocus(agentFocuses: Array<{ runId: string; resourceId: ResourcePartitionId | null; detail: string }>): void {
    const focusMap = new Map(agentFocuses.map((f) => [f.runId, f]))
    for (const agentId of prevActiveAgentIds) {
      const focus = focusMap.get(agentId)
      scene.setAgentActorFocus(agentId, focus?.resourceId ?? null)
      scene.setAgentActorStatus(agentId, focus?.detail ?? '')
    }
    for (const procId of prevActiveProcessIds) {
      const focus = focusMap.get(procId)
      scene.setAgentActorFocus(`proc:${procId}`, focus?.resourceId ?? null)
      scene.setAgentActorStatus(`proc:${procId}`, focus?.detail ?? '')
    }
  }

  function setGrowth(assetsCount: number, skillsCount: number, textOutputs: number): void {
    scene.events.emit('set-growth', { assetsCount, skillsCount, textOutputs })
  }

  function cycleTheme(): void {
    scene.events.emit('cycle-theme')
  }

  function dispose(): void {
    prevActiveAgentIds.clear()
    prevActiveProcessIds.clear()
  }

  return {
    push,
    applyFocus,
    setGrowth,
    cycleTheme,
    dispose
  }
}

export type TelemetryFeed = ReturnType<typeof createTelemetryFeed>
