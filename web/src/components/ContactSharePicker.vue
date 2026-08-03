<script setup lang="ts">
import { LoaderCircle, Search, UserRound } from 'lucide-vue-next'
import { onBeforeUnmount, ref, watch } from 'vue'
import { searchContacts } from '../api/contacts'
import type { ContactSearchResult } from '../api/types'

const emit = defineEmits<{
  select: [contact: ContactSearchResult]
}>()

const query = ref('')
const results = ref<ContactSearchResult[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
let timer: number | null = null
let requestId = 0

watch(query, (value) => {
  if (timer !== null) window.clearTimeout(timer)
  const normalized = value.trim()
  if (normalized.length < 2) {
    results.value = []
    loading.value = false
    error.value = null
    return
  }
  timer = window.setTimeout(() => void runSearch(normalized), 180)
})

onBeforeUnmount(() => {
  if (timer !== null) window.clearTimeout(timer)
})

async function runSearch(value: string) {
  const currentRequest = ++requestId
  loading.value = true
  error.value = null
  try {
    const contacts = await searchContacts(value)
    if (currentRequest === requestId) results.value = contacts
  } catch (requestError) {
    if (currentRequest !== requestId) return
    results.value = []
    error.value =
      requestError instanceof Error
        ? requestError.message
        : 'Não foi possível buscar contatos.'
  } finally {
    if (currentRequest === requestId) loading.value = false
  }
}
</script>

<template>
  <div class="fixed bottom-20 left-3 right-3 z-30 overflow-hidden rounded-lg bg-panel text-ink shadow-2xl ring-1 ring-black/10 sm:absolute sm:bottom-14 sm:left-0 sm:right-auto sm:w-[22rem]">
    <div class="border-b border-line p-3">
      <label class="relative block">
        <Search class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
        <input
          v-model="query"
          autofocus
          type="search"
          class="h-10 w-full rounded-md border border-line bg-panel-muted pl-9 pr-3 text-sm outline-none focus:border-fluvius-500"
          placeholder="Buscar nome ou telefone"
        />
      </label>
    </div>
    <div class="soft-scrollbar max-h-72 overflow-y-auto py-1.5">
      <div v-if="loading" class="grid h-20 place-items-center text-ink-muted">
        <LoaderCircle class="h-5 w-5 animate-spin" />
      </div>
      <p v-else-if="error" class="px-4 py-5 text-center text-xs text-danger-strong">
        {{ error }}
      </p>
      <p v-else-if="query.trim().length < 2" class="px-4 py-5 text-center text-xs text-ink-muted">
        Digite ao menos dois caracteres.
      </p>
      <p v-else-if="!results.length" class="px-4 py-5 text-center text-xs text-ink-muted">
        Nenhum contato encontrado.
      </p>
      <button
        v-for="contact in results"
        :key="contact.id"
        type="button"
        class="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-panel-muted"
        @click="emit('select', contact)"
      >
        <img
          v-if="contact.profile_picture_url"
          :src="contact.profile_picture_url"
          :alt="contact.display_name"
          class="h-9 w-9 rounded-full object-cover"
        />
        <span v-else class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-canvas text-ink-muted">
          <UserRound class="h-4 w-4" />
        </span>
        <span class="min-w-0">
          <span class="block truncate text-sm font-medium">{{ contact.display_name }}</span>
          <span class="block truncate text-xs text-ink-muted">+{{ contact.phone_number }}</span>
        </span>
      </button>
    </div>
  </div>
</template>
