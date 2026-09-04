<script setup lang="ts">
import {
  AlertCircle,
  Building2,
  Eye,
  EyeOff,
  LoaderCircle,
  Lock,
  Mail,
} from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getTenantLogin } from '../api/auth'
import type { TenantLogin } from '../api/auth'
import { APP_NAME, APP_VERSION } from '../config/app'
import ThemeMenu from '../components/ThemeMenu.vue'
import { useAuthStore } from '../stores/authStore'

const email = ref('')
const password = ref('')
const showPassword = ref(false)
const route = useRoute()
const tenant = ref<TenantLogin | null>(null)
const tenantLoading = ref(false)
const tenantUnavailable = ref(false)
const tenantSlug = computed(() => {
  const value = route.params.tenantSlug
  return typeof value === 'string' ? value : undefined
})
const error = ref(
  route.query.session === 'expired' ? 'Sua sessão expirou. Entre novamente.' : '',
)
const auth = useAuthStore()
const router = useRouter()
const canSubmit = computed(
  () =>
    !auth.loading &&
    !tenantLoading.value &&
    !tenantUnavailable.value &&
    email.value.trim().length > 0 &&
    password.value.length > 0,
)

onMounted(async () => {
  if (!tenantSlug.value) return
  tenantLoading.value = true
  try {
    tenant.value = await getTenantLogin(tenantSlug.value)
  } catch {
    tenantUnavailable.value = true
    error.value = 'Este acesso não está disponível. Confirme o link com o administrador.'
  } finally {
    tenantLoading.value = false
  }
})

async function submit() {
  if (!canSubmit.value) return
  error.value = ''
  try {
    await auth.signIn(email.value.trim(), password.value, tenantSlug.value)
    router.push('/app/conversations')
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : 'Não foi possível entrar'
  }
}
</script>

<template>
  <main class="relative flex min-h-screen items-center justify-center bg-canvas px-4 py-8 text-ink sm:px-6">
    <div class="absolute right-4 top-4 sm:right-6 sm:top-6">
      <ThemeMenu />
    </div>

    <section class="w-full max-w-md rounded-xl border border-line bg-panel p-6 shadow-lg shadow-black/[0.08] sm:p-8 dark:shadow-black/25">
      <header class="mb-8 flex items-center gap-3">
        <div class="grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-fluvius-700 font-bold text-white">
          F
        </div>
        <div class="min-w-0">
          <p class="truncate text-lg font-semibold text-ink">{{ APP_NAME }}</p>
          <p class="text-xs text-ink-muted">Atendimento em tempo real</p>
        </div>
      </header>

      <div class="mb-7">
        <h1 class="text-2xl font-semibold text-ink">Entrar</h1>
        <p class="mt-1.5 text-sm text-ink-muted">
          Use suas credenciais para acessar os atendimentos.
        </p>
      </div>

      <div
        v-if="tenantLoading"
        class="mb-5 flex items-center gap-2.5 rounded-lg border border-line bg-panel-muted px-3.5 py-3 text-sm text-ink-secondary"
      >
        <LoaderCircle class="h-4 w-4 animate-spin text-fluvius-600" />
        Validando empresa...
      </div>
      <div
        v-else-if="tenant"
        class="mb-5 flex items-center gap-2.5 rounded-lg border border-fluvius-600/25 bg-fluvius-50 px-3.5 py-3 text-sm text-fluvius-800 dark:bg-fluvius-700/15 dark:text-emerald-100"
      >
        <Building2 class="h-4 w-4 shrink-0 text-fluvius-600" />
        <span>
          Acesso exclusivo de <strong class="font-semibold">{{ tenant.name }}</strong>
        </span>
      </div>
      <div
        v-else-if="tenantUnavailable"
        class="mb-5 flex items-start gap-2.5 rounded-lg border border-danger/30 bg-danger-soft px-3.5 py-3 text-sm text-danger-strong"
      >
        <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
        <span>Empresa indisponível ou link inválido.</span>
      </div>

      <form class="space-y-4" @submit.prevent="submit">
        <div>
          <label for="login-email" class="mb-1.5 block text-sm font-medium text-ink-secondary">
            E-mail
          </label>
          <div class="relative">
            <Mail
              class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
            />
            <input
              id="login-email"
              v-model="email"
              type="email"
              required
              autocomplete="username"
              placeholder="voce@empresa.com"
              :disabled="tenantUnavailable || tenantLoading"
              class="w-full rounded-lg border border-line-strong bg-canvas py-2.5 pl-10 pr-3 text-ink outline-none transition placeholder:text-ink-faint focus:border-fluvius-600 focus:bg-panel focus:ring-4 focus:ring-fluvius-600/15 disabled:cursor-not-allowed disabled:bg-panel-muted disabled:text-ink-faint"
            />
          </div>
        </div>

        <div>
          <label for="login-password" class="mb-1.5 block text-sm font-medium text-ink-secondary">
            Senha
          </label>
          <div class="relative">
            <Lock
              class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
            />
            <input
              id="login-password"
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              required
              autocomplete="current-password"
              placeholder="••••••••"
              :disabled="tenantUnavailable || tenantLoading"
              class="w-full rounded-lg border border-line-strong bg-canvas py-2.5 pl-10 pr-11 text-ink outline-none transition placeholder:text-ink-faint focus:border-fluvius-600 focus:bg-panel focus:ring-4 focus:ring-fluvius-600/15 disabled:cursor-not-allowed disabled:bg-panel-muted disabled:text-ink-faint"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-lg text-ink-faint transition hover:bg-panel-muted hover:text-ink-secondary"
              :aria-label="showPassword ? 'Ocultar senha' : 'Mostrar senha'"
              :disabled="tenantUnavailable || tenantLoading"
              @click="showPassword = !showPassword"
            >
              <EyeOff v-if="showPassword" class="h-4 w-4" />
              <Eye v-else class="h-4 w-4" />
            </button>
          </div>
        </div>

        <div
          v-if="error"
          class="flex items-start gap-2.5 rounded-lg border border-danger/30 bg-danger-soft px-3.5 py-3 text-sm text-danger-strong"
          role="alert"
        >
          <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
          <span>{{ error }}</span>
        </div>

        <button
          type="submit"
          class="mt-2 flex w-full items-center justify-center gap-2 rounded-lg bg-fluvius-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-fluvius-800 focus:outline-none focus:ring-4 focus:ring-fluvius-600/25 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!canSubmit"
        >
          <LoaderCircle v-if="auth.loading" class="h-4 w-4 animate-spin" />
          {{ auth.loading ? 'Entrando...' : 'Entrar' }}
        </button>
      </form>

      <p class="mt-8 text-center text-xs text-ink-faint">
        Problemas para entrar? Fale com o administrador da sua empresa.
      </p>
      <p class="mt-4 text-center text-[11px] text-ink-faint">v{{ APP_VERSION }}</p>
    </section>
  </main>
</template>
