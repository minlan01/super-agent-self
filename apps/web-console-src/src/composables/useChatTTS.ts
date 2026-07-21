import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'
import { useEdgeTTS } from '@/composables/useEdgeTTS'
import { useTTSSettings } from '@/composables/useTTSSettings'
import type { ChatMessage } from '@/api/types'

export function useChatTTS() {
  const { t } = useI18n()
  const message = useMessage()

  const playingMessageId = ref<string | null>(null)
  const lastPlayedMessageId = ref<string | null>(null)

  const { speak: ttsSpeak, stop: ttsStop, isLoading: ttsIsLoading } = useEdgeTTS({
    voice: 'zh-CN',
  })
  const { settings: ttsSettings } = useTTSSettings()

  function stopTTS() {
    ttsStop()
    playingMessageId.value = null
  }

  async function playTTS(msg: ChatMessage) {
    const content = msg.content || ''
    if (!content.trim()) return

    // If already playing this message, stop it
    if (playingMessageId.value === msg.id) {
      stopTTS()
      return
    }

    // Stop any current playback
    stopTTS()

    try {
      playingMessageId.value = msg.id || null

      const voice = ttsSettings.value.voice || 'zh-CN'
      const rate = ttsSettings.value.rate ?? 1.0
      const volume = ttsSettings.value.volume ?? 1.0
      const pitch = ttsSettings.value.pitch ?? 1.0

      await ttsSpeak(content, { voice, rate, volume, pitch })
    } catch (err) {
      console.error('[useChatTTS] TTS error:', err)
      message.error(t('pages.chat.tts.error'))
      stopTTS()
    }
  }

  return {
    playingMessageId,
    lastPlayedMessageId,
    ttsIsLoading,
    ttsSettings,
    playTTS,
    stopTTS,
  }
}
