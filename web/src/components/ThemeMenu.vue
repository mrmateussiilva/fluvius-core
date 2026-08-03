<script setup lang="ts">
import { Check, Monitor, Moon, Sun } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useTheme, type ThemePreference } from '../composables/useTheme'

const props = withDefaults(
  defineProps<{
    inverted?: boolean
    placement?: 'top' | 'bottom'
  }>(),
  {
    inverted: false,
    placement: 'bottom',
  },
)

const root = ref<HTMLElement | null>(null)
const open = ref(false)
const { preference, resolvedTheme, setThemePreference } = useTheme()
const CurrentIcon = computed(() => (resolvedTheme.value === 'dark' ? Moon : Sun))
const options: Array<{ value: ThemePreference; label: string; icon: typeof Sun }> = [
  { value: 'system', label: 'Sistema', icon: Monitor },
  { value: 'light', label: 'Claro', icon: Sun },
  { value: 'dark', label: 'Escuro', icon: Moon },
]

function selectTheme(value: ThemePreference) {
  setThemePreference(value)
  open.value = false
}

function closeOnOutsideClick(event: MouseEvent) {
  if (!root.value?.contains(event.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('click', closeOnOutsideClick))
onBeforeUnmount(() => document.removeEventListener('click', closeOnOutsideClick))
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="grid h-9 w-9 place-items-center rounded-lg transition focus:outline-none focus:ring-2 focus:ring-fluvius-500/40"
      :class="
        props.inverted
          ? 'text-emerald-50/70 hover:bg-white/10 hover:text-white'
          : 'text-ink-muted hover:bg-panel-muted hover:text-ink'
      "
      title="Aparência"
      aria-label="Alterar aparência"
      :aria-expanded="open"
      @click.stop="open = !open"
    >
      <component :is="CurrentIcon" class="h-4 w-4" />
    </button>

    <div
      v-if="open"
      class="absolute z-50 w-40 overflow-hidden rounded-lg border border-line bg-panel-raised p-1 text-ink shadow-xl shadow-black/15"
      :class="props.placement === 'top' ? 'bottom-0 left-12' : 'right-0 top-11'"
      role="menu"
    >
      <button
        v-for="option in options"
        :key="option.value"
        type="button"
        class="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm transition hover:bg-panel-muted"
        role="menuitemradio"
        :aria-checked="preference === option.value"
        @click="selectTheme(option.value)"
      >
        <component :is="option.icon" class="h-4 w-4 text-ink-muted" />
        <span>{{ option.label }}</span>
        <Check
          v-if="preference === option.value"
          class="ml-auto h-4 w-4 text-fluvius-600 dark:text-fluvius-500"
        />
      </button>
    </div>
  </div>
</template>
