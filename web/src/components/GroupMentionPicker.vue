<script setup lang="ts">
type MentionCandidate = {
  key: string
  kind: 'member' | 'contact'
  phone_number: string
  label: string
  subtitle: string
}

defineProps<{
  activeIndex: number
  candidates: MentionCandidate[]
  loading: boolean
  error: string | null
  query: string
}>()
const emit = defineEmits<{
  hover: [index: number]
  select: [candidate: MentionCandidate]
}>()
</script>

<template>
  <div class="absolute bottom-full left-0 z-30 mb-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-lg border border-black/5 bg-panel p-2 shadow-2xl">
    <div class="border-b border-line px-2 pb-2 pt-1">
      <p class="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
        Mencionar ou referenciar
      </p>
      <p v-if="query" class="mt-0.5 truncate text-xs text-ink-faint">
        @{{ query }}
      </p>
    </div>
    <button
      v-for="(candidate, index) in candidates"
      :key="candidate.key"
      class="mt-1 flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition"
      :class="
        index === activeIndex
          ? 'bg-fluvius-50 text-fluvius-900 dark:text-emerald-100'
          : 'hover:bg-panel-muted'
      "
      @mouseenter="emit('hover', index)"
      @mousedown.prevent="emit('select', candidate)"
    >
      <span
        class="grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-semibold"
        :class="
          candidate.kind === 'member'
            ? 'bg-success-soft text-success-strong'
            : 'bg-info-soft text-info-strong'
        "
      >
        {{ candidate.label.slice(0, 1).toUpperCase() }}
      </span>
      <span class="min-w-0">
        <span class="block truncate text-sm font-medium text-ink">
          {{ candidate.label }}
        </span>
        <span class="mt-0.5 block truncate text-xs text-ink-muted">
          {{ candidate.subtitle }}
        </span>
      </span>
      <span
        class="ml-auto shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold"
        :class="
          candidate.kind === 'member'
            ? 'bg-success-soft text-success-strong'
            : 'bg-info-soft text-info-strong'
        "
      >
        {{ candidate.kind === 'member' ? 'Grupo' : 'Contato' }}
      </span>
    </button>
    <p
      v-if="loading"
      class="px-2 py-4 text-center text-xs text-ink-muted"
    >
      Buscando contatos...
    </p>
    <p
      v-else-if="error"
      class="px-2 py-4 text-center text-xs text-danger"
    >
      {{ error }}
    </p>
    <p
      v-else-if="!candidates.length"
      class="px-2 py-4 text-center text-xs text-ink-muted"
    >
      Nenhum participante ou contato encontrado.
    </p>
  </div>
</template>
