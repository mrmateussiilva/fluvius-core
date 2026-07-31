<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  BadgeCheck,
  CalendarDays,
  CheckCircle2,
  History,
  MessageCircle,
  RefreshCw,
  Users,
  X,
} from 'lucide-vue-next'
import type { ContactDetail, Conversation } from '../api/types'

const props = defineProps<{
  conversation: Conversation
  contact: ContactDetail | null
  loading: boolean
  error: string | null
}>()
const emit = defineEmits<{ close: []; refresh: [] }>()
const imageFailed = ref(false)

watch(
  () => props.contact?.profile_picture_url,
  () => (imageFailed.value = false),
)

const displayName = computed(
  () => props.contact?.display_name || props.conversation.contact_name || props.conversation.contact_phone,
)
const initials = computed(() =>
  displayName.value
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join(''),
)

function formatPhone(value: string) {
  const digits = value.replace(/\D/g, '')
  if (digits.length === 13 && digits.startsWith('55')) {
    return `+55 (${digits.slice(2, 4)}) ${digits.slice(4, 9)}-${digits.slice(9)}`
  }
  if (digits.length === 12 && digits.startsWith('55')) {
    return `+55 (${digits.slice(2, 4)}) ${digits.slice(4, 8)}-${digits.slice(8)}`
  }
  return value.startsWith('+') ? value : `+${value}`
}

function formatDate(value: string | null | undefined) {
  if (!value) return 'Não disponível'
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
</script>

<template>
  <aside class="absolute inset-0 z-30 flex h-full w-full shrink-0 flex-col border-l border-[#d8dcdf] bg-[#f7f8f8] xl:static xl:w-[340px]">
    <header class="flex min-h-[64px] items-center justify-between border-b border-[#d8dcdf] bg-[#f0f2f5] px-4 py-3">
      <h2 class="text-sm font-semibold text-[#111b21]">
        {{
          (contact?.kind || conversation.contact_kind || 'direct') === 'group'
            ? 'Dados do grupo'
            : 'Dados do contato'
        }}
      </h2>
      <button class="rounded-full p-2 text-[#667781] transition hover:bg-black/5" title="Fechar" @click="emit('close')">
        <X class="h-4 w-4" />
      </button>
    </header>

    <div class="soft-scrollbar min-h-0 flex-1 overflow-y-auto">
      <div class="bg-white px-5 py-6 text-center shadow-sm">
        <img
          v-if="contact?.profile_picture_url && !imageFailed"
          :src="contact.profile_picture_url"
          :alt="displayName"
          class="mx-auto h-24 w-24 rounded-full object-cover ring-4 ring-[#f0f2f5]"
          referrerpolicy="no-referrer"
          @error="imageFailed = true"
        />
        <div
          v-else
          class="mx-auto grid h-24 w-24 place-items-center rounded-full bg-gradient-to-br from-fluvius-100 to-emerald-200 text-2xl font-semibold text-fluvius-800 ring-4 ring-[#f0f2f5]"
        >
          {{ initials }}
        </div>
        <h3 class="mt-3 text-lg font-semibold text-[#111b21]">{{ displayName }}</h3>
        <p class="mt-1 text-sm text-[#667781]">
          {{
            (contact?.kind || conversation.contact_kind || 'direct') === 'group'
              ? 'Grupo do WhatsApp'
              : formatPhone(contact?.phone_number || conversation.contact_phone)
          }}
        </p>
        <div
          v-if="(contact?.kind || conversation.contact_kind || 'direct') === 'group'"
          class="mt-2 inline-flex items-center gap-1 rounded-full bg-violet-50 px-2 py-1 text-xs font-medium text-violet-700"
        >
          Conversa em grupo
        </div>
        <div
          v-else-if="contact?.is_on_whatsapp === true"
          class="mt-2 inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700"
        >
          <CheckCircle2 class="h-3.5 w-3.5" /> Número no WhatsApp
        </div>
        <div
          v-else-if="contact?.is_on_whatsapp === false"
          class="mt-2 inline-flex rounded-full bg-rose-50 px-2 py-1 text-xs font-medium text-rose-700"
        >
          Número não encontrado no WhatsApp
        </div>
      </div>

      <div v-if="loading && !contact" class="m-4 rounded-xl bg-white py-10 text-center text-sm text-[#667781] shadow-sm">
        Consultando dados do WhatsApp...
      </div>
      <p v-if="error" class="m-4 rounded-lg bg-rose-50 p-3 text-xs text-rose-700 ring-1 ring-rose-100">
        {{ error }}
      </p>

      <template v-if="contact">
        <div v-if="contact.verified_name || contact.business_name" class="mx-4 mt-4 rounded-xl bg-white p-4 shadow-sm">
          <div class="flex items-center gap-2 text-sm font-medium text-slate-700">
            <BadgeCheck class="h-4 w-4 text-emerald-600" /> Perfil comercial
          </div>
          <p class="mt-1 text-sm text-slate-600">
            {{ contact.verified_name || contact.business_name }}
          </p>
        </div>

        <div v-if="contact.about" class="mx-4 mt-3 rounded-xl bg-white p-4 shadow-sm">
          <p class="text-[10px] font-medium uppercase tracking-[0.12em] text-[#8696a0]">Recado</p>
          <p class="mt-1.5 text-sm text-[#3b4a54]">{{ contact.about }}</p>
        </div>

        <div class="mx-4 mt-3 grid grid-cols-2 gap-2">
          <div class="rounded-xl bg-white p-3 shadow-sm">
            <div class="flex items-center gap-1.5 text-xs text-slate-500">
              <MessageCircle class="h-3.5 w-3.5" /> Atendimentos
            </div>
            <p class="mt-1 text-xl font-semibold">{{ contact.conversation_count }}</p>
          </div>
          <div class="rounded-xl bg-white p-3 shadow-sm">
            <div class="flex items-center gap-1.5 text-xs text-slate-500">
              <History class="h-3.5 w-3.5" /> Finalizados
            </div>
            <p class="mt-1 text-xl font-semibold">{{ contact.closed_conversation_count }}</p>
          </div>
        </div>

        <dl class="mx-4 mt-3 space-y-4 rounded-xl bg-white p-4 text-sm shadow-sm">
          <div>
            <dt class="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
              <CalendarDays class="h-3.5 w-3.5" /> Primeira interação
            </dt>
            <dd class="mt-1 text-slate-700">{{ formatDate(contact.first_interaction_at) }}</dd>
          </div>
          <div>
            <dt class="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
              <CalendarDays class="h-3.5 w-3.5" /> Última interação
            </dt>
            <dd class="mt-1 text-slate-700">{{ formatDate(contact.last_interaction_at) }}</dd>
          </div>
        </dl>

        <div
          v-if="(contact?.kind || conversation.contact_kind || 'direct') === 'group' && contact?.group_member_count !== null"
          class="mx-4 mt-3 rounded-xl bg-white p-3 shadow-sm"
        >
          <div class="flex items-center gap-1.5 text-xs text-slate-500">
            <Users class="h-3.5 w-3.5" /> Membros
          </div>
          <p class="mt-1 text-xl font-semibold text-fluvius-700">
            {{ contact.group_member_count }}
          </p>
        </div>
        <div
          v-if="contact?.group_members && contact.group_members.length"
          class="mx-4 mt-3 rounded-xl bg-white p-3 shadow-sm max-h-48 overflow-y-auto"
        >
          <div class="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-400 mb-2">
            <Users class="h-3.5 w-3.5" /> Participantes
          </div>
          <ul class="space-y-1">
            <li
              v-for="member in contact.group_members"
              :key="member.phone_number"
              class="flex items-center gap-2 text-sm text-slate-700 py-1"
            >
              <span
                class="grid h-7 w-7 place-items-center rounded-full bg-fluvius-50 text-fluvius-700 text-xs font-medium"
              >
                {{ member.phone_number.slice(-4) }}
              </span>
              <span class="truncate font-medium">
                {{ member.name || member.phone_number }}
              </span>
              <span
                v-if="member.is_admin"
                class="ml-auto rounded-full bg-violet-50 px-1.5 py-0.5 text-[9px] font-semibold text-violet-700"
              >
                Admin
              </span>
            </li>
          </ul>
        </div>
        <button
          class="mx-4 mt-3 flex items-center justify-center gap-2 rounded-lg border border-[#d1d7db] bg-white px-3 py-2.5 text-sm font-medium text-fluvius-700 shadow-sm transition hover:bg-fluvius-50 disabled:opacity-50"
          :disabled="loading"
          @click="emit('refresh')"
        >
          <RefreshCw class="h-4 w-4" :class="loading ? 'animate-spin' : ''" />
          {{
            loading
              ? 'Atualizando...'
              : (contact?.kind || conversation.contact_kind || 'direct') === 'group'
                ? 'Atualizar dados do grupo'
                : 'Atualizar dados do WhatsApp'
          }}
        </button>
        <p class="px-5 pb-5 pt-3 text-center text-[11px] leading-4 text-[#8696a0]">
          {{
            (contact?.kind || conversation.contact_kind || 'direct') === 'group'
              ? 'Grupos entram na fila quando alguém envia mensagem. Respostas vão para o grupo.'
              : 'Alguns dados podem não aparecer devido às configurações de privacidade do contato.'
          }}
        </p>
      </template>
    </div>
  </aside>
</template>
