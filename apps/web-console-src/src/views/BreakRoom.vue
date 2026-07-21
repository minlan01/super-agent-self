<script setup lang="ts">
import { ref } from 'vue'
import { NCard, NButton } from 'naive-ui'

const clicks = ref(0)
const messages = [
  'Agents need rest too.',
  'Grab a virtual coffee!',
  'Pixel art is art.',
  'This room has the best Wi‑Fi.',
  '404 coffee not found.',
  'Shhh… agents are compiling.',
  'Easter egg #' + Math.floor(Math.random() * 9000 + 1000),
  'You found the break room!',
]

function nextMessage() {
  clicks.value++
}
</script>

<template>
  <div class="break-room-page">
    <NCard class="break-room-card" :bordered="false">
      <div class="break-room-inner">
        <span class="break-room-icon">🍵</span>
        <h2 class="pixel-text break-room-title">Break Room</h2>
        <p class="break-room-sub">Even command centers need downtime.</p>
        <p class="break-room-easter">
          {{ messages[Math.min(clicks, messages.length - 1)] ?? messages[messages.length - 1] }}
        </p>
        <NButton secondary size="small" @click="nextMessage">
          Get Hint
        </NButton>
      </div>
    </NCard>
  </div>
</template>

<style scoped>
.break-room-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 60vh;
}

.break-room-card {
  max-width: 420px;
  text-align: center;
  background: linear-gradient(135deg, var(--bg-deepest), var(--bg-deep));
  border: 1px solid var(--line-glow);
  box-shadow: 0 0 40px var(--accent-glow);
}

.break-room-inner {
  padding: 32px 16px;
}

.break-room-icon {
  font-size: 48px;
  display: block;
  margin-bottom: 16px;
}

.break-room-title {
  font-family: var(--font-display);
  font-size: 24px;
  color: var(--accent);
  text-shadow: 0 0 12px var(--accent-glow);
  margin: 0 0 8px;
}

.break-room-sub {
  color: var(--muted);
  font-size: 14px;
  margin: 0 0 12px;
}

.break-room-easter {
  font-family: var(--font-display);
  font-size: 16px;
  color: var(--tone-warm);
  margin: 0 0 16px;
  min-height: 24px;
}
</style>
