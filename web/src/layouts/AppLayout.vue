<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  Building2,
  Check,
  Columns3,
  DatabaseBackup,
  LogOut,
  MessageCircle,
  Settings,
  UserRoundCog,
  Zap,
} from 'lucide-vue-next'
import { listAvailableTenants } from '../api/auth'
import type { AvailableTenant } from '../api/types'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/authStore'
import { useRealtimeStore } from '../stores/realtimeStore'

const auth = useAuthStore()
const realtime = useRealtimeStore()
const router = useRouter()
const userInitial = computed(() => auth.user?.name?.trim().charAt(0).toUpperCase() || 'U')
const availableTenants = ref<AvailableTenant[]>([])
const tenantMenuOpen = ref(false)
const tenantSwitching = ref(false)
const tenantError = ref('')

onMounted(async () => {
  try {
    await auth.restore()
    availableTenants.value = await listAvailableTenants()
  } catch {
    availableTenants.value = []
  }
})

async function logout() {
  realtime.disconnect()
  await auth.signOut()
  await router.push('/login')
}

async function selectTenant(tenantId: string) {
  tenantMenuOpen.value = false
  if (tenantId === auth.user?.tenant_id || tenantSwitching.value) return
  tenantSwitching.value = true
  tenantError.value = ''
  realtime.disconnect()
  try {
    await auth.switchTenant(tenantId)
    window.location.replace('/app/conversations')
  } catch (exception) {
    tenantError.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível trocar de empresa'
    tenantMenuOpen.value = true
    realtime.connect()
  } finally {
    tenantSwitching.value = false
  }
}
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-[#e9edef]">
    <nav class="relative flex w-[68px] shrink-0 flex-col items-center bg-fluvius-900 py-4 text-emerald-50/70 shadow-xl shadow-slate-900/10">
      <div
        class="mb-2 grid h-10 w-10 place-items-center rounded-xl bg-white font-bold text-fluvius-800 shadow-sm"
        :title="`Fluvius Core · ${auth.user?.tenant_name || 'Empresa'}`"
      >
        F
      </div>
      <button
        class="mb-5 grid h-8 w-10 place-items-center rounded-lg text-emerald-50/70 transition hover:bg-white/10 hover:text-white"
        :class="{ 'cursor-default': availableTenants.length < 2 }"
        :disabled="availableTenants.length < 2 || tenantSwitching"
        :title="availableTenants.length > 1 ? `Trocar empresa · atual: ${auth.user?.tenant_name}` : auth.user?.tenant_name"
        @click="tenantMenuOpen = !tenantMenuOpen"
      >
        <Building2 class="h-4 w-4" />
      </button>
      <div
        v-if="tenantMenuOpen"
        class="absolute left-14 top-14 z-50 w-72 overflow-hidden rounded-xl border border-slate-200 bg-white text-slate-700 shadow-2xl"
      >
        <div class="border-b border-slate-100 px-4 py-3">
          <p class="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Trocar empresa
          </p>
          <p class="mt-0.5 truncate text-sm font-medium text-slate-800">
            {{ auth.user?.tenant_name }}
          </p>
        </div>
        <p
          v-if="tenantError"
          class="border-b border-rose-100 bg-rose-50 px-4 py-2 text-xs text-rose-700"
        >
          {{ tenantError }}
        </p>
        <button
          v-for="tenant in availableTenants"
          :key="tenant.id"
          class="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm hover:bg-slate-50"
          @click="selectTenant(tenant.id)"
        >
          <span class="min-w-0">
            <span class="block truncate font-medium">{{ tenant.name }}</span>
            <span class="block truncate text-xs text-slate-400">{{ tenant.slug }}</span>
          </span>
          <Check
            v-if="tenant.id === auth.user?.tenant_id"
            class="h-4 w-4 shrink-0 text-fluvius-700"
          />
        </button>
      </div>
      <RouterLink
        class="mb-1.5 rounded-xl p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/conversations"
        title="Conversas"
      >
        <MessageCircle class="h-5 w-5" />
      </RouterLink>
      <RouterLink
        v-if="auth.user?.role === 'admin'"
        class="mb-1.5 rounded-xl p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/team-board"
        title="Quadro da equipe"
      >
        <Columns3 class="h-5 w-5" />
      </RouterLink>
      <RouterLink
        class="mb-1.5 rounded-xl p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/quick-replies"
        title="Respostas rápidas"
      >
        <Zap class="h-5 w-5" />
      </RouterLink>
      <RouterLink
        v-if="auth.user?.role === 'admin'"
        class="rounded-xl p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/settings/channels"
        title="Canais"
      >
        <Settings class="h-5 w-5" />
      </RouterLink>
      <RouterLink
        v-if="auth.user?.role === 'admin'"
        class="mt-1.5 rounded-xl p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/settings/users"
        title="Usuários"
      >
        <UserRoundCog class="h-5 w-5" />
      </RouterLink>
      <RouterLink
        v-if="auth.user?.role === 'admin'"
        class="mt-1.5 rounded-xl p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/settings/sync"
        title="Sincronização"
      >
        <DatabaseBackup class="h-5 w-5" />
      </RouterLink>
      <RouterLink
        v-if="auth.user?.is_platform_admin"
        class="mt-1.5 rounded-xl p-2.5 text-amber-200 transition hover:bg-white/10 hover:text-amber-100"
        active-class="bg-amber-400/15 text-amber-100 shadow-sm"
        to="/app/platform/tenants"
        title="Administração Fluvius"
      >
        <Building2 class="h-5 w-5" />
      </RouterLink>
      <div class="mt-auto grid h-9 w-9 place-items-center rounded-full bg-emerald-700 text-xs font-semibold text-white ring-2 ring-white/10" :title="auth.user?.name || 'Usuário'">
        {{ userInitial }}
      </div>
      <button class="mt-2 rounded-xl p-2.5 transition hover:bg-white/10 hover:text-white" title="Sair" @click="logout">
        <LogOut class="h-5 w-5" />
      </button>
    </nav>
    <main class="min-w-0 flex-1 overflow-hidden">
      <RouterView />
    </main>
  </div>
</template>
