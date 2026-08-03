<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CircleAlert, Pause, Play } from 'lucide-vue-next'

const props = defineProps<{
  src: string
  fileName: string
}>()

const audio = ref<HTMLAudioElement | null>(null)
const playing = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const failed = ref(false)
const playerId = crypto.randomUUID()
const speedOptions = [1, 1.5, 2] as const
const speed = ref<(typeof speedOptions)[number]>(loadSpeed())
const progress = computed(() =>
  duration.value > 0 ? Math.min(100, (currentTime.value / duration.value) * 100) : 0,
)

function loadSpeed(): (typeof speedOptions)[number] {
  try {
    const saved = Number(localStorage.getItem('fluvius_audio_speed'))
    return speedOptions.includes(saved as (typeof speedOptions)[number])
      ? (saved as (typeof speedOptions)[number])
      : 1
  } catch {
    return 1
  }
}

function formatTime(value: number) {
  if (!Number.isFinite(value) || value < 0) return '0:00'
  const minutes = Math.floor(value / 60)
  const seconds = Math.floor(value % 60)
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}

async function togglePlayback() {
  const element = audio.value
  if (!element || failed.value) return
  if (!element.paused) {
    element.pause()
    return
  }
  window.dispatchEvent(
    new CustomEvent('fluvius:audio-play', { detail: playerId }),
  )
  element.playbackRate = speed.value
  try {
    await element.play()
  } catch {
    failed.value = true
  }
}

function seek(event: Event) {
  const element = audio.value
  if (!element || duration.value <= 0) return
  const value = Number((event.target as HTMLInputElement).value)
  element.currentTime = (value / 100) * duration.value
  currentTime.value = element.currentTime
}

function cycleSpeed() {
  const index = speedOptions.indexOf(speed.value)
  speed.value = speedOptions[(index + 1) % speedOptions.length]
  if (audio.value) audio.value.playbackRate = speed.value
  try {
    localStorage.setItem('fluvius_audio_speed', String(speed.value))
  } catch {
    // Browsers may block local storage in restricted contexts.
  }
}

function updateMetadata() {
  duration.value = Number.isFinite(audio.value?.duration)
    ? audio.value?.duration || 0
    : 0
}

function updateTime() {
  currentTime.value = audio.value?.currentTime || 0
}

function pauseFromAnotherPlayer(event: Event) {
  if ((event as CustomEvent<string>).detail !== playerId) audio.value?.pause()
}

watch(
  () => props.src,
  () => {
    playing.value = false
    currentTime.value = 0
    duration.value = 0
    failed.value = false
  },
)

onMounted(() => {
  window.addEventListener('fluvius:audio-play', pauseFromAnotherPlayer)
})

onBeforeUnmount(() => {
  audio.value?.pause()
  window.removeEventListener('fluvius:audio-play', pauseFromAnotherPlayer)
})
</script>

<template>
  <div
    class="flex w-64 max-w-full items-center gap-2 rounded-lg bg-ink/[0.045] px-2 py-2 sm:w-72"
    :aria-label="`Áudio ${fileName}`"
  >
    <audio
      ref="audio"
      :src="src"
      preload="metadata"
      @loadedmetadata="updateMetadata"
      @durationchange="updateMetadata"
      @timeupdate="updateTime"
      @play="playing = true"
      @pause="playing = false"
      @ended="playing = false"
      @error="failed = true"
    />
    <button
      type="button"
      class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-fluvius-600 text-white transition hover:bg-fluvius-700 disabled:bg-disabled"
      :disabled="failed"
      :title="playing ? 'Pausar áudio' : 'Reproduzir áudio'"
      @click="togglePlayback"
    >
      <CircleAlert v-if="failed" class="h-4 w-4" />
      <Pause v-else-if="playing" class="h-4 w-4 fill-current" />
      <Play v-else class="ml-0.5 h-4 w-4 fill-current" />
    </button>
    <div class="min-w-0 flex-1">
      <input
        type="range"
        min="0"
        max="100"
        step="0.1"
        :value="progress"
        :disabled="failed || duration <= 0"
        class="h-1.5 w-full cursor-pointer accent-fluvius-600 disabled:cursor-default"
        aria-label="Posição do áudio"
        @input="seek"
      />
      <div class="mt-1 flex items-center justify-between gap-2 text-[10px] text-ink-muted">
        <span v-if="failed">Áudio indisponível</span>
        <span v-else>{{ formatTime(currentTime) }} / {{ formatTime(duration) }}</span>
        <button
          type="button"
          class="rounded-full bg-ink/[0.07] px-2 py-0.5 font-semibold text-ink transition hover:bg-ink/[0.12]"
          title="Alterar velocidade"
          @click="cycleSpeed"
        >
          {{ speed.toString().replace('.', ',') }}x
        </button>
      </div>
    </div>
  </div>
</template>
