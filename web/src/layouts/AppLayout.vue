<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  AlertTriangle,
  Building2,
  Check,
  ChevronRight,
  Columns3,
  ContactRound,
  DatabaseBackup,
  HeartPulse,
  LogOut,
  Menu,
  MessageCircle,
  Settings,
  UserRoundCog,
  X,
  Zap,
} from 'lucide-vue-next'
import { listAvailableTenants } from '../api/auth'
import type { AvailableTenant } from '../api/types'
import { useRoute, useRouter } from 'vue-router'
import { APP_NAME, APP_VERSION } from '../config/app'
import ThemeMenu from '../components/ThemeMenu.vue'
import { useAuthStore } from '../stores/authStore'
import { useConversationStore } from '../stores/conversationStore'
import { useOperationalStore } from '../stores/operationalStore'
import { useRealtimeStore } from '../stores/realtimeStore'

const auth = useAuthStore()
const conversations = useConversationStore()
const operations = useOperationalStore()
const realtime = useRealtimeStore()
const router = useRouter()
const route = useRoute()

const userInitial = computed(
  () => auth.user?.name?.trim().charAt(0).toUpperCase() || 'U',
)
const availableTenants = ref<AvailableTenant[]>([])
const tenantMenuOpen = ref(false)
const tenantSwitching = ref(false)
const tenantError = ref('')
const mobileMenuOpen = ref(false)

const isChatActiveOnMobile = computed(
  () =>
    route.path === '/app/conversations' && Boolean(conversations.selectedId),
)

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

function ensureRealtimeConnection() {
  realtime.ensureConnected()
}

onMounted(async () => {
  try {
    await auth.restore()
    if (auth.user?.role === 'admin') operations.startPolling()
    availableTenants.value = await listAvailableTenants()
  } catch {
    availableTenants.value = []
  }
  if (auth.user) realtime.connect()
  document.addEventListener('visibilitychange', ensureRealtimeConnection)
  window.addEventListener('online', ensureRealtimeConnection)
})

onBeforeUnmount(() => {
  operations.stopPolling()
  document.removeEventListener('visibilitychange', ensureRealtimeConnection)
  window.removeEventListener('online', ensureRealtimeConnection)
  realtime.disconnect()
})

async function logout() {
  mobileMenuOpen.value = false
  const tenantSlug = auth.user?.tenant_slug
  realtime.disconnect()
  await auth.signOut()
  await router.push(tenantSlug ? `/login/${tenantSlug}` : '/login')
}

async function selectTenant(tenantId: string) {
  tenantMenuOpen.value = false
  mobileMenuOpen.value = false
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

function navigateFromMobile(path: string) {
  mobileMenuOpen.value = false
  void router.push(path)
}
</script>

<template>
  <div class="flex h-screen h-[100dvh] overflow-hidden bg-canvas text-ink">
    <!-- Desktop Sidebar (Hidden on Mobile) -->
    <nav
      class="relative hidden w-[68px] shrink-0 flex-col items-center bg-nav py-4 text-emerald-50/70 shadow-lg shadow-black/10 md:flex"
    >
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
        :title="
          availableTenants.length > 1
            ? `Trocar empresa · atual: ${auth.user?.tenant_name}`
            : auth.user?.tenant_name
        "
        @click="tenantMenuOpen = !tenantMenuOpen"
      >
        <Building2 class="h-4 w-4" />
      </button>

      <!-- Tenant Switcher Dropdown (Desktop) -->
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
      <div
        class="grid h-9 w-9 place-items-center rounded-full bg-emerald-700 text-xs font-semibold text-white ring-2 ring-white/10"
        :title="auth.user?.name || 'Usuário'"
      >
        {{ userInitial }}
      </div>
      <button
        class="mt-2 rounded-lg p-2.5 transition hover:bg-white/10 hover:text-white"
        title="Sair"
        @click="logout"
      >
        <LogOut class="h-5 w-5" />
      </button>
    </nav>

    <!-- Main Content Area -->
    <main class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <!-- Top Operational Alert Banner (if any) -->
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

      <!-- Router View Container -->
      <div
        class="flex h-full min-h-0 flex-1 flex-col overflow-hidden"
        :class="{ 'pb-16 md:pb-0': !isChatActiveOnMobile }"
      >
        <RouterView />
      </div>

      <!-- Mobile Bottom Navigation Bar (Hidden when inside an active chat on mobile) -->
      <nav
        v-if="!isChatActiveOnMobile"
        class="fixed bottom-0 left-0 right-0 z-40 flex h-16 items-center justify-around border-t border-white/10 bg-nav px-2 text-emerald-50/70 shadow-2xl md:hidden"
      >
        <RouterLink
          to="/app/conversations"
          class="flex flex-1 flex-col items-center justify-center gap-1 py-1 transition"
          active-class="font-semibold text-white"
        >
          <MessageCircle class="h-5 w-5" />
          <span class="text-[11px] leading-none">Conversas</span>
        </RouterLink>

        <RouterLink
          to="/app/contacts"
          class="flex flex-1 flex-col items-center justify-center gap-1 py-1 transition"
          active-class="font-semibold text-white"
        >
          <ContactRound class="h-5 w-5" />
          <span class="text-[11px] leading-none">Contatos</span>
        </RouterLink>

        <RouterLink
          v-if="auth.user?.role === 'admin'"
          to="/app/team-board"
          class="flex flex-1 flex-col items-center justify-center gap-1 py-1 transition"
          active-class="font-semibold text-white"
        >
          <Columns3 class="h-5 w-5" />
          <span class="text-[11px] leading-none">Quadro</span>
        </RouterLink>

        <RouterLink
          v-else
          to="/app/quick-replies"
          class="flex flex-1 flex-col items-center justify-center gap-1 py-1 transition"
          active-class="font-semibold text-white"
        >
          <Zap class="h-5 w-5" />
          <span class="text-[11px] leading-none">Respostas</span>
        </RouterLink>

        <button
          class="relative flex flex-1 flex-col items-center justify-center gap-1 py-1 transition hover:text-white"
          :class="{ 'font-semibold text-white': mobileMenuOpen }"
          @click="mobileMenuOpen = true"
        >
          <Menu class="h-5 w-5" />
          <span class="text-[11px] leading-none">Mais</span>
          <span
            v-if="operationalAlert"
            class="absolute right-6 top-1 h-2 w-2 rounded-full ring-2 ring-nav"
            :class="
              operations.health?.status === 'critical' || operations.error
                ? 'bg-rose-400'
                : 'bg-amber-300'
            "
          />
        </button>
      </nav>
    </main>

    <!-- Mobile Drawer / Menu Sheet (Bottom Drawer) -->
    <div
      v-if="mobileMenuOpen"
      class="fixed inset-0 z-50 flex flex-col justify-end bg-black/60 backdrop-blur-sm md:hidden"
      @click.self="mobileMenuOpen = false"
    >
      <div
        class="flex max-h-[85vh] flex-col overflow-hidden rounded-t-2xl border-t border-line bg-panel shadow-2xl"
      >
        <!-- Header -->
        <div class="flex items-center justify-between border-b border-line px-5 py-4">
          <div class="flex items-center gap-3">
            <div
              class="grid h-10 w-10 place-items-center rounded-full bg-emerald-700 text-sm font-semibold text-white"
            >
              {{ userInitial }}
            </div>
            <div>
              <p class="font-semibold text-ink">{{ auth.user?.name }}</p>
              <p class="text-xs text-ink-muted">
                {{ auth.user?.tenant_name }} ·
                {{ auth.user?.role === 'admin' ? 'Administrador' : 'Atendente' }}
              </p>
            </div>
          </div>
          <button
            class="grid h-9 w-9 place-items-center rounded-full text-ink-muted transition hover:bg-black/5"
            @click="mobileMenuOpen = false"
          >
            <X class="h-5 w-5" />
          </button>
        </div>

        <!-- Scrollable Options List -->
        <div class="soft-scrollbar min-h-0 flex-1 overflow-y-auto p-4 space-y-1">
          <!-- Tenant Switcher (if multiple) -->
          <div v-if="availableTenants.length > 1" class="mb-3 rounded-xl border border-line p-3">
            <p class="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-faint">
              Trocar de Empresa
            </p>
            <div class="space-y-1">
              <button
                v-for="tenant in availableTenants"
                :key="tenant.id"
                class="flex w-full items-center justify-between rounded-lg p-2 text-left text-sm transition hover:bg-panel-muted"
                :class="{ 'bg-panel-muted font-medium': tenant.id === auth.user?.tenant_id }"
                @click="selectTenant(tenant.id)"
              >
                <div>
                  <p class="font-medium text-ink">{{ tenant.name }}</p>
                  <p class="text-xs text-ink-faint">{{ tenant.slug }}</p>
                </div>
                <Check
                  v-if="tenant.id === auth.user?.tenant_id"
                  class="h-4 w-4 text-fluvius-700"
                />
              </button>
            </div>
          </div>

          <!-- Quick Replies (for admin / agent) -->
          <button
            class="flex w-full items-center justify-between rounded-xl p-3 text-left transition hover:bg-panel-muted"
            @click="navigateFromMobile('/app/quick-replies')"
          >
            <div class="flex items-center gap-3">
              <div class="grid h-9 w-9 place-items-center rounded-lg bg-amber-500/10 text-amber-600">
                <Zap class="h-5 w-5" />
              </div>
              <div>
                <p class="text-sm font-medium text-ink">Respostas Rápidas</p>
                <p class="text-xs text-ink-muted">Gerenciar modelos e atalhos</p>
              </div>
            </div>
            <ChevronRight class="h-4 w-4 text-ink-faint" />
          </button>

          <!-- Admin section -->
          <template v-if="auth.user?.role === 'admin'">
            <button
              class="flex w-full items-center justify-between rounded-xl p-3 text-left transition hover:bg-panel-muted"
              @click="navigateFromMobile('/app/team-board')"
            >
              <div class="flex items-center gap-3">
                <div class="grid h-9 w-9 place-items-center rounded-lg bg-emerald-500/10 text-emerald-600">
                  <Columns3 class="h-5 w-5" />
                </div>
                <div>
                  <p class="text-sm font-medium text-ink">Quadro da Equipe</p>
                  <p class="text-xs text-ink-muted">Visão geral e redistribuição</p>
                </div>
              </div>
              <ChevronRight class="h-4 w-4 text-ink-faint" />
            </button>

            <button
              class="flex w-full items-center justify-between rounded-xl p-3 text-left transition hover:bg-panel-muted"
              @click="navigateFromMobile('/app/settings/channels')"
            >
              <div class="flex items-center gap-3">
                <div class="grid h-9 w-9 place-items-center rounded-lg bg-blue-500/10 text-blue-600">
                  <Settings class="h-5 w-5" />
                </div>
                <div>
                  <p class="text-sm font-medium text-ink">Canais WhatsApp</p>
                  <p class="text-xs text-ink-muted">Conexões e instâncias</p>
                </div>
              </div>
              <ChevronRight class="h-4 w-4 text-ink-faint" />
            </button>

            <button
              class="flex w-full items-center justify-between rounded-xl p-3 text-left transition hover:bg-panel-muted"
              @click="navigateFromMobile('/app/settings/users')"
            >
              <div class="flex items-center gap-3">
                <div class="grid h-9 w-9 place-items-center rounded-lg bg-purple-500/10 text-purple-600">
                  <UserRoundCog class="h-5 w-5" />
                </div>
                <div>
                  <p class="text-sm font-medium text-ink">Usuários e Acesso</p>
                  <p class="text-xs text-ink-muted">Atendentes e permissões</p>
                </div>
              </div>
              <ChevronRight class="h-4 w-4 text-ink-faint" />
            </button>

            <button
              class="flex w-full items-center justify-between rounded-xl p-3 text-left transition hover:bg-panel-muted"
              @click="navigateFromMobile('/app/settings/sync')"
            >
              <div class="flex items-center gap-3">
                <div class="grid h-9 w-9 place-items-center rounded-lg bg-cyan-500/10 text-cyan-600">
                  <DatabaseBackup class="h-5 w-5" />
                </div>
                <div>
                  <p class="text-sm font-medium text-ink">Sincronização</p>
                  <p class="text-xs text-ink-muted">Histórico e contatos</p>
                </div>
              </div>
              <ChevronRight class="h-4 w-4 text-ink-faint" />
            </button>

            <button
              class="flex w-full items-center justify-between rounded-xl p-3 text-left transition hover:bg-panel-muted"
              @click="navigateFromMobile('/app/settings/operations')"
            >
              <div class="flex items-center gap-3">
                <div class="grid h-9 w-9 place-items-center rounded-lg bg-rose-500/10 text-rose-600">
                  <HeartPulse class="h-5 w-5" />
                </div>
                <div>
                  <p class="text-sm font-medium text-ink">Saúde Operacional</p>
                  <p class="text-xs text-ink-muted">Workers, filas e diagnósticos</p>
                </div>
              </div>
              <span
                v-if="operationalAlert"
                class="rounded-full bg-rose-500 px-2 py-0.5 text-[10px] font-semibold text-white"
              >
                Alerta
              </span>
              <ChevronRight v-else class="h-4 w-4 text-ink-faint" />
            </button>
          </template>

          <button
            v-if="auth.user?.is_platform_admin"
            class="flex w-full items-center justify-between rounded-xl p-3 text-left transition hover:bg-panel-muted"
            @click="navigateFromMobile('/app/platform/tenants')"
          >
            <div class="flex items-center gap-3">
              <div class="grid h-9 w-9 place-items-center rounded-lg bg-amber-500/10 text-amber-600">
                <Building2 class="h-5 w-5" />
              </div>
              <div>
                <p class="text-sm font-medium text-ink">Administração Fluvius</p>
                <p class="text-xs text-ink-muted">Gestão global de empresas</p>
              </div>
            </div>
            <ChevronRight class="h-4 w-4 text-ink-faint" />
          </button>

          <!-- Theme & Logout -->
          <div class="border-t border-line pt-3 mt-3">
            <div class="flex items-center justify-between px-3 py-2">
              <span class="text-sm text-ink-secondary">Tema da Interface</span>
              <ThemeMenu />
            </div>

            <button
              class="flex w-full items-center gap-3 rounded-xl p-3 text-left text-danger transition hover:bg-danger-soft"
              @click="logout"
            >
              <LogOut class="h-5 w-5" />
              <span class="text-sm font-medium">Sair da Conta</span>
            </button>
          </div>
        </div>

        <!-- Footer Info -->
        <div class="border-t border-line bg-panel-muted px-5 py-3 text-center text-xs text-ink-faint">
          {{ APP_NAME }} v{{ APP_VERSION }}
        </div>
      </div>
    </div>
  </div>
</template>
