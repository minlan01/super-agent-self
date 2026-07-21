import Phaser from 'phaser'
import { LibraryScene } from '@/museum/runtime/scene/LibraryScene'

export interface MuseumGameOptions {
  /** DOM parent element — must exist and have dimensions */
  parent: HTMLElement
  /** Game width (default: 1920) */
  width?: number
  /** Game height (default: 1080) */
  height?: number
  /** If true, canvas background is transparent (default: true) */
  transparent?: boolean
}

export interface MuseumGameHandle {
  /** The Phaser.Game instance */
  game: Phaser.Game
  /** The LibraryScene instance (only available after create phase) */
  scene: LibraryScene
  /** Resolves when the scene's create() has finished */
  ready: () => Promise<LibraryScene>
}

/**
 * Create a Phaser.Game with LibraryScene mounted to a DOM parent.
 * Returns a handle with game/scene references and lifecycle control.
 *
 * Usage:
 *   const handle = createMuseumGame({ parent: container.value! })
 *   // later, when scene is ready:
 *   const scene = await handle.ready()
 *   // cleanup:
 *   destroyMuseumGame(handle)
 */
export function createMuseumGame(options: MuseumGameOptions): MuseumGameHandle {
  const {
    parent,
    width = 1920,
    height = 1080,
    transparent = true
  } = options

  const scene = new LibraryScene()

  const game = new Phaser.Game({
    type: Phaser.AUTO,
    parent,
    transparent,
    scale: {
      mode: Phaser.Scale.FIT,
      autoCenter: Phaser.Scale.CENTER_BOTH,
      width,
      height
    },
    input: {
      activePointers: 3
    }
  })

  // Note: Phaser's scene manager handles scene lifecycle.
  // We register LibraryScene after game creation so it starts immediately.
  // The scene is available via game.scene.getScene('LibraryScene') after create().
  game.scene.add('LibraryScene', scene, false)
  game.scene.start('LibraryScene')

  const ready = (): Promise<LibraryScene> => {
    return new Promise((resolve) => {
      if (game.scene.isActive('LibraryScene')) {
        resolve(game.scene.getScene('LibraryScene') as LibraryScene)
      } else {
        game.events.once('ready', () => {
          resolve(game.scene.getScene('LibraryScene') as LibraryScene)
        })
      }
    })
  }

  return { game, scene, ready }
}

/**
 * Destroy a Phaser game created by createMuseumGame.
 * Safe to call multiple times.
 */
export function destroyMuseumGame(handle: MuseumGameHandle | null): void {
  if (!handle) return
  const { game } = handle
  try {
    game.destroy(true)
  } catch {
    // game may already be destroyed
  }
}
