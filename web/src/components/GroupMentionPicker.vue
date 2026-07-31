<script setup lang="ts">
import type { GroupMemberResponse } from '../api/types'

defineProps<{
  activeIndex: number
  members: GroupMemberResponse[]
  query: string
}>()
const emit = defineEmits<{
  hover: [index: number]
  select: [member: GroupMemberResponse]
}>()

function memberLabel(member: GroupMemberResponse) {
  return member.name || member.phone_number
}
</script>

<template>
  <div class="absolute bottom-full left-0 z-30 mb-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-black/5 bg-white p-2 shadow-2xl">
    <div class="border-b border-[#e9edef] px-2 pb-2 pt-1">
      <p class="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#667781]">
        Mencionar participante
      </p>
      <p v-if="query" class="mt-0.5 truncate text-xs text-[#8696a0]">
        @{{ query }}
      </p>
    </div>
    <button
      v-for="(member, index) in members"
      :key="member.phone_number"
      class="mt-1 flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition"
      :class="
        index === activeIndex
          ? 'bg-fluvius-50 text-fluvius-900'
          : 'hover:bg-[#f0f2f5]'
      "
      @mouseenter="emit('hover', index)"
      @mousedown.prevent="emit('select', member)"
    >
      <span class="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-emerald-50 text-xs font-semibold text-emerald-700">
        {{ memberLabel(member).slice(0, 1).toUpperCase() }}
      </span>
      <span class="min-w-0">
        <span class="block truncate text-sm font-medium text-[#111b21]">
          {{ memberLabel(member) }}
        </span>
        <span class="mt-0.5 block truncate text-xs text-[#667781]">
          {{ member.phone_number }}{{ member.is_admin ? ' · Admin' : '' }}
        </span>
      </span>
    </button>
    <p
      v-if="!members.length"
      class="px-2 py-4 text-center text-xs text-[#667781]"
    >
      Nenhum participante encontrado.
    </p>
  </div>
</template>
