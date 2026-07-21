import { ref } from 'vue'

export function useAudioRecorder() {
  const isRecording = ref(false)
  const audioBlob = ref<Blob | null>(null)
  let mediaRecorder: MediaRecorder | null = null
  let chunks: Blob[] = []

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' })
      chunks = []
      mediaRecorder.ondataavailable = (e: BlobEvent) => {
        if (e.data.size > 0) chunks.push(e.data)
      }
      mediaRecorder.onstop = () => {
        audioBlob.value = new Blob(chunks, { type: 'audio/webm' })
        chunks = []
        stream.getTracks().forEach(t => t.stop())
      }
      mediaRecorder.start()
      isRecording.value = true
    } catch (err) {
      console.error('Failed to start recording:', err)
      throw err
    }
  }

  function stopRecording(): Blob | null {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop()
    }
    isRecording.value = false
    return audioBlob.value
  }

  return { isRecording, audioBlob, startRecording, stopRecording }
}
