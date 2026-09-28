<script setup lang="ts">
import { Check, Monitor, Moon, Sun } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useTheme, type ThemePreference } from '../composables/useTheme'

const props = withDefaults(
  defineProps<{
    inverted?: boolean
    placement?: 'top' | 'bottom'
    showLabel?: boolean
  }>(),
  {
    inverted: false,
    placement: 'bottom',
    showLabel: false,
  },
)

const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const open = ref(false)
const position = ref({ left: 8, top: 8 })
const { preference, resolvedTheme, setThemePreference } = useTheme()
const CurrentIcon = computed(() => (resolvedTheme.value === 'dark' ? Moon : Sun))
const menuWidth = 160
const menuHeight = 128
const options: Array<{ value: ThemePreference; label: string; icon: typeof Sun }> = [
  { value: 'system', label: 'Sistema', icon: Monitor },
  { value: 'light', label: 'Claro', icon: Sun },
  { value: 'dark', label: 'Escuro', icon: Moon },
]

function selectTheme(value: ThemePreference) {
  setThemePreference(value)
  open.value = false
}

function updateMenuPosition(force = false) {
  if ((!open.value && !force) || !trigger.value) return
  const rect = trigger.value.getBoundingClientRect()
  const margin = 8
  let left: number
  let top: number

  if (props.placement === 'top') {
    left = rect.right + margin
    if (left + menuWidth > window.innerWidth - margin) {
      left = rect.left - menuWidth - margin
    }
    top = rect.bottom - menuHeight
  } else {
    left = rect.right - menuWidth
    top = rect.bottom + margin
    if (top + menuHeight > window.innerHeight - margin) {
      top = rect.top - menuHeight - margin
    }
  }

  position.value = {
    left: Math.max(margin, Math.min(left, window.innerWidth - menuWidth - margin)),
    top: Math.max(margin, Math.min(top, window.innerHeight - menuHeight - margin)),
  }
}

function toggleMenu() {
  if (open.value) {
    open.value = false
    return
  }
  updateMenuPosition(true)
  open.value = true
}

function handleViewportChange() {
  updateMenuPosition()
}

function closeOnOutsideClick(event: MouseEvent) {
  const target = event.target as Node
  if (!root.value?.contains(target) && !menu.value?.contains(target)) {
    open.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', closeOnOutsideClick)
  window.addEventListener('resize', handleViewportChange)
  window.addEventListener('scroll', handleViewportChange, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', closeOnOutsideClick)
  window.removeEventListener('resize', handleViewportChange)
  window.removeEventListener('scroll', handleViewportChange, true)
})
</script>

<template>
  <div ref="root" class="relative" :class="{ 'w-full': props.showLabel }">
    <button
      ref="trigger"
      type="button"
      class="motion-interactive rounded-lg focus:outline-none focus:ring-2 focus:ring-fluvius-500/40"
      :class="
        [
          props.inverted
            ? 'text-ink-muted hover:bg-panel-muted hover:text-ink'
            : 'text-ink-muted hover:bg-panel-muted hover:text-ink',
          props.showLabel
            ? 'flex h-11 w-full items-center justify-start gap-3 px-3'
            : 'grid h-9 w-9 place-items-center',
        ]
      "
      title="Aparência"
      aria-label="Alterar aparência"
      :aria-expanded="open"
      aria-controls="theme-options"
      @click.stop="toggleMenu"
    >
      <component :is="CurrentIcon" class="h-4 w-4" />
      <span v-if="props.showLabel" class="text-sm font-medium">Aparência</span>
    </button>

    <Teleport to="body">
      <Transition name="motion-pop">
        <div
          v-if="open"
          id="theme-options"
          ref="menu"
          class="fixed z-[1000] w-40 origin-top-left overflow-hidden rounded-lg border border-line bg-panel-raised p-1 text-ink shadow-xl shadow-scrim/15"
          :style="{ left: `${position.left}px`, top: `${position.top}px` }"
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
      </Transition>
    </Teleport>
  </div>
</template>
