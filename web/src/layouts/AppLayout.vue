<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  AlertTriangle,
  Building2,
  Check,
  Columns3,
  ContactRound,
  DatabaseBackup,
  HeartPulse,
  LogOut,
  MessageCircle,
  Settings,
  UserRoundCog,
  Zap,
} from 'lucide-vue-next'
import { listAvailableTenants } from '../api/auth'
import type { AvailableTenant } from '../api/types'
import { useRouter } from 'vue-router'
import { APP_NAME, APP_VERSION } from '../config/app'
import ThemeMenu from '../components/ThemeMenu.vue'
import { useAuthStore } from '../stores/authStore'
import { useOperationalStore } from '../stores/operationalStore'
import { useRealtimeStore } from '../stores/realtimeStore'

const auth = useAuthStore()
const operations = useOperationalStore()
const realtime = useRealtimeStore()
const router = useRouter()
const userInitial = computed(() => auth.user?.name?.trim().charAt(0).toUpperCase() || 'U')
const availableTenants = ref<AvailableTenant[]>([])
const tenantMenuOpen = ref(false)
const tenantSwitching = ref(false)
const tenantError = ref('')
const operationalAlert = computed(() => {
  if (operations.error) return operations.error
  if (operations.health?.status === 'critical') {
    return operations.health.issues[0] || 'A operação exige ação imediata.'
  }
  if (operations.health?.status === 'attention') {
    return operations.health.issues[0] || 'A operação exige atenção.'
  }
  return ''
})
const operationalAlertClass = computed(() =>
  operations.health?.status === 'critical' || operations.error
    ? 'border-danger/30 bg-danger-soft text-danger-strong'
    : 'border-warning/30 bg-warning-soft text-warning-strong',
)

onMounted(async () => {
  try {
    await auth.restore()
    if (auth.user?.role === 'admin') operations.startPolling()
    availableTenants.value = await listAvailableTenants()
  } catch {
    availableTenants.value = []
  }
})

onBeforeUnmount(() => {
  operations.stopPolling()
})

async function logout() {
  const tenantSlug = auth.user?.tenant_slug
  realtime.disconnect()
  await auth.signOut()
  await router.push(tenantSlug ? `/login/${tenantSlug}` : '/login')
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
  <div class="flex h-screen overflow-hidden bg-canvas text-ink">
    <nav class="relative flex w-[68px] shrink-0 flex-col items-center bg-nav py-4 text-emerald-50/70 shadow-lg shadow-black/10">
      <div
        class="mb-2 grid h-10 w-10 place-items-center rounded-lg bg-panel font-bold text-fluvius-800 shadow-sm"
        :title="`${APP_NAME} v${APP_VERSION} · ${auth.user?.tenant_name || 'Empresa'}`"
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
        class="absolute left-14 top-14 z-50 w-72 overflow-hidden rounded-lg border border-line bg-panel-raised text-ink-secondary shadow-2xl shadow-black/20"
      >
        <div class="border-b border-line px-4 py-3">
          <p class="text-xs font-semibold uppercase tracking-wider text-ink-faint">
            Trocar empresa
          </p>
          <p class="mt-0.5 truncate text-sm font-medium text-ink">
            {{ auth.user?.tenant_name }}
          </p>
        </div>
        <p
          v-if="tenantError"
          class="border-b border-danger/20 bg-danger-soft px-4 py-2 text-xs text-danger-strong"
        >
          {{ tenantError }}
        </p>
        <button
          v-for="tenant in availableTenants"
          :key="tenant.id"
          class="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm hover:bg-panel-muted"
          @click="selectTenant(tenant.id)"
        >
          <span class="min-w-0">
            <span class="block truncate font-medium">{{ tenant.name }}</span>
            <span class="block truncate text-xs text-ink-faint">{{ tenant.slug }}</span>
          </span>
          <Check
            v-if="tenant.id === auth.user?.tenant_id"
            class="h-4 w-4 shrink-0 text-fluvius-700"
          />
        </button>
      </div>
      <RouterLink
        class="mb-1.5 rounded-lg p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/conversations"
        title="Conversas"
      >
        <MessageCircle class="h-5 w-5" />
      </RouterLink>
      <RouterLink
        class="mb-1.5 rounded-lg p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/contacts"
        title="Contatos"
      >
        <ContactRound class="h-5 w-5" />
      </RouterLink>
      <RouterLink
        v-if="auth.user?.role === 'admin'"
        class="mb-1.5 rounded-lg p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/team-board"
        title="Quadro da equipe"
      >
        <Columns3 class="h-5 w-5" />
      </RouterLink>
      <RouterLink
        class="mb-1.5 rounded-lg p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/quick-replies"
        title="Respostas rápidas"
      >
        <Zap class="h-5 w-5" />
      </RouterLink>
      <RouterLink
        v-if="auth.user?.role === 'admin'"
        class="rounded-lg p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/settings/channels"
        title="Canais"
      >
        <Settings class="h-5 w-5" />
      </RouterLink>
      <RouterLink
        v-if="auth.user?.role === 'admin'"
        class="mt-1.5 rounded-lg p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/settings/users"
        title="Usuários"
      >
        <UserRoundCog class="h-5 w-5" />
      </RouterLink>
      <RouterLink
        v-if="auth.user?.role === 'admin'"
        class="mt-1.5 rounded-lg p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/settings/sync"
        title="Sincronização"
      >
        <DatabaseBackup class="h-5 w-5" />
      </RouterLink>
      <RouterLink
        v-if="auth.user?.role === 'admin'"
        class="relative mt-1.5 rounded-lg p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/settings/operations"
        title="Saúde operacional"
      >
        <HeartPulse class="h-5 w-5" />
        <span
          v-if="operationalAlert"
          class="absolute right-2 top-2 h-2 w-2 rounded-full ring-2 ring-fluvius-900"
          :class="
            operations.health?.status === 'critical' || operations.error
              ? 'bg-rose-400'
              : 'bg-amber-300'
          "
        />
      </RouterLink>
      <RouterLink
        v-if="auth.user?.is_platform_admin"
        class="mt-1.5 rounded-lg p-2.5 text-amber-200 transition hover:bg-white/10 hover:text-amber-100"
        active-class="bg-amber-400/15 text-amber-100 shadow-sm"
        to="/app/platform/tenants"
        title="Administração Fluvius"
      >
        <Building2 class="h-5 w-5" />
      </RouterLink>
      <ThemeMenu class="mb-2 mt-auto" inverted placement="top" />
      <div
        class="mb-3 select-none text-[10px] font-semibold leading-none text-emerald-50/45"
        :title="`${APP_NAME} v${APP_VERSION}`"
      >
        v{{ APP_VERSION }}
      </div>
      <div class="grid h-9 w-9 place-items-center rounded-full bg-emerald-700 text-xs font-semibold text-white ring-2 ring-white/10" :title="auth.user?.name || 'Usuário'">
        {{ userInitial }}
      </div>
      <button class="mt-2 rounded-lg p-2.5 transition hover:bg-white/10 hover:text-white" title="Sair" @click="logout">
        <LogOut class="h-5 w-5" />
      </button>
    </nav>
    <main class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <RouterLink
        v-if="auth.user?.role === 'admin' && operationalAlert"
        class="flex shrink-0 items-center gap-2 border-b px-4 py-2 text-xs font-medium"
        :class="operationalAlertClass"
        to="/app/settings/operations"
      >
        <AlertTriangle class="h-4 w-4 shrink-0" />
        <span class="truncate">{{ operationalAlert }}</span>
        <span class="ml-auto shrink-0 font-semibold">Ver saúde</span>
      </RouterLink>
      <div class="min-h-0 flex-1 overflow-hidden">
        <RouterView />
      </div>
    </main>
  </div>
</template>
