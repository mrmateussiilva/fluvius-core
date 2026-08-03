<script setup lang="ts">
import { computed, ref } from 'vue'
import { Clock3, Heart, Leaf, Lightbulb, Smile, Utensils, Volleyball } from 'lucide-vue-next'

type EmojiCategory = {
  id: string
  label: string
  emojis: string[]
}

const emit = defineEmits<{
  select: [emoji: string]
}>()

const RECENT_EMOJIS_KEY = 'fluvius.recent-emojis'
const categories: EmojiCategory[] = [
  {
    id: 'faces',
    label: 'Rostos e pessoas',
    emojis: [
      '😀', '😃', '😄', '😁', '😆', '😅', '😂', '🤣', '😊', '😇',
      '🙂', '🙃', '😉', '😌', '😍', '🥰', '😘', '😋', '😛', '😜',
      '🤪', '🤨', '🧐', '🤓', '😎', '🤩', '🥳', '😏', '😒', '😔',
      '😢', '😭', '😤', '😡', '🤯', '😳', '🥺', '😱', '🤗', '🤔',
      '🤭', '🤫', '🤥', '😶', '😴', '🤤', '😷', '🤒', '🤠', '😈',
      '👍', '👎', '👌', '✌️', '🤞', '🤟', '🤙', '👏', '🙌', '🙏',
    ],
  },
  {
    id: 'hearts',
    label: 'Corações e símbolos',
    emojis: [
      '❤️', '🩷', '🧡', '💛', '💚', '💙', '🩵', '💜', '🤎', '🖤',
      '🤍', '💔', '❣️', '💕', '💞', '💓', '💗', '💖', '💘', '💝',
      '💯', '💢', '💥', '💫', '💦', '💨', '🕳️', '💬', '👁️‍🗨️', '🗨️',
      '✅', '❌', '❗', '❓', '⚠️', '♻️', '✨', '🔥', '⭐', '🌟',
    ],
  },
  {
    id: 'animals',
    label: 'Animais e natureza',
    emojis: [
      '🐶', '🐱', '🐭', '🐹', '🐰', '🦊', '🐻', '🐼', '🐨', '🐯',
      '🦁', '🐮', '🐷', '🐸', '🐵', '🙈', '🙉', '🙊', '🐔', '🐧',
      '🐦', '🦄', '🐝', '🦋', '🐞', '🐢', '🐍', '🦎', '🐙', '🐬',
      '🌸', '🌹', '🌻', '🌱', '🌿', '🍀', '🌵', '🌴', '🌈', '☀️',
    ],
  },
  {
    id: 'food',
    label: 'Comidas e bebidas',
    emojis: [
      '🍎', '🍊', '🍋', '🍉', '🍇', '🍓', '🫐', '🍒', '🥭', '🍍',
      '🥑', '🍅', '🥕', '🌽', '🍞', '🧀', '🍔', '🍟', '🍕', '🌭',
      '🌮', '🍿', '🍩', '🍪', '🎂', '🍫', '🍬', '☕', '🍺', '🥂',
    ],
  },
  {
    id: 'activities',
    label: 'Atividades e viagens',
    emojis: [
      '⚽', '🏀', '🏈', '⚾', '🎾', '🏐', '🎱', '🏓', '🥊', '🏆',
      '🎯', '🎮', '🎲', '🎸', '🎤', '🎧', '🎬', '🎨', '🚗', '🚌',
      '🏍️', '✈️', '🚀', '🚲', '🏠', '🏖️', '⛰️', '🏙️', '🎉', '🎁',
    ],
  },
  {
    id: 'objects',
    label: 'Objetos',
    emojis: [
      '⌚', '📱', '💻', '⌨️', '🖥️', '📷', '💡', '🔦', '📚', '📌',
      '✏️', '📝', '📅', '📦', '✉️', '📧', '☎️', '🔔', '🔒', '🔑',
      '🛠️', '🧲', '🧪', '🩺', '💊', '🛒', '💰', '💳', '📈', '📍',
    ],
  },
]

const activeCategory = ref('faces')
const recentEmojis = ref<string[]>(loadRecentEmojis())
const visibleCategory = computed(() => {
  if (activeCategory.value === 'recent') {
    return {
      id: 'recent',
      label: 'Usados recentemente',
      emojis: recentEmojis.value,
    }
  }
  return categories.find((category) => category.id === activeCategory.value) || categories[0]
})

function loadRecentEmojis(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(RECENT_EMOJIS_KEY) || '[]')
    return Array.isArray(value)
      ? value.filter((emoji): emoji is string => typeof emoji === 'string').slice(0, 30)
      : []
  } catch {
    return []
  }
}

function selectEmoji(emoji: string) {
  recentEmojis.value = [
    emoji,
    ...recentEmojis.value.filter((recent) => recent !== emoji),
  ].slice(0, 30)
  try {
    localStorage.setItem(RECENT_EMOJIS_KEY, JSON.stringify(recentEmojis.value))
  } catch {
    // The picker remains usable when browser storage is unavailable.
  }
  emit('select', emoji)
}

const categoryIcons = {
  recent: Clock3,
  faces: Smile,
  hearts: Heart,
  animals: Leaf,
  food: Utensils,
  activities: Volleyball,
  objects: Lightbulb,
}
</script>

<template>
  <div
    class="absolute bottom-14 left-0 z-30 flex h-72 w-[min(20rem,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-lg bg-panel text-ink shadow-2xl ring-1 ring-black/5"
    role="dialog"
    aria-label="Selecionar emoji"
    @click.stop
  >
    <div class="grid grid-cols-7 border-b border-line px-2 pt-1.5">
      <button
        v-if="recentEmojis.length"
        type="button"
        class="grid h-9 place-items-center border-b-2 transition"
        :class="
          activeCategory === 'recent'
            ? 'border-fluvius-600 text-fluvius-700'
            : 'border-transparent text-ink-faint hover:text-ink-secondary'
        "
        title="Recentes"
        @click="activeCategory = 'recent'"
      >
        <Clock3 class="h-4 w-4" />
      </button>
      <button
        v-for="category in categories"
        :key="category.id"
        type="button"
        class="grid h-9 place-items-center border-b-2 transition"
        :class="
          activeCategory === category.id
            ? 'border-fluvius-600 text-fluvius-700'
            : 'border-transparent text-ink-faint hover:text-ink-secondary'
        "
        :title="category.label"
        @click="activeCategory = category.id"
      >
        <component :is="categoryIcons[category.id as keyof typeof categoryIcons]" class="h-4 w-4" />
      </button>
    </div>
    <p class="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
      {{ visibleCategory.label }}
    </p>
    <div class="soft-scrollbar grid flex-1 grid-cols-8 content-start gap-0.5 overflow-y-auto px-2 pb-2">
      <button
        v-for="emoji in visibleCategory.emojis"
        :key="emoji"
        type="button"
        class="grid aspect-square place-items-center rounded-md text-[22px] transition hover:bg-panel-muted"
        :title="emoji"
        @click="selectEmoji(emoji)"
      >
        {{ emoji }}
      </button>
    </div>
  </div>
</template>
