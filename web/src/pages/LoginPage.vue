<script setup lang="ts">
import {
  AlertCircle,
  Building2,
  Eye,
  EyeOff,
  LoaderCircle,
  Lock,
  Mail,
  MessageCircle,
} from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getTenantLogin } from '../api/auth'
import type { TenantLogin } from '../api/auth'
import { APP_NAME, APP_VERSION } from '../config/app'
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
  <div class="relative flex min-h-screen overflow-hidden bg-[#e9edef]">
    <div
      class="pointer-events-none absolute inset-0 opacity-70"
      aria-hidden="true"
      style="
        background-image:
          radial-gradient(circle at 12% 18%, rgba(33, 161, 121, 0.18), transparent 42%),
          radial-gradient(circle at 88% 12%, rgba(8, 63, 54, 0.12), transparent 36%),
          radial-gradient(circle at 70% 88%, rgba(22, 133, 106, 0.14), transparent 40%);
      "
    />

    <div class="relative z-10 mx-auto flex w-full max-w-6xl flex-1 items-center justify-center p-4 sm:p-6 lg:p-10">
      <div
        class="grid w-full overflow-hidden rounded-2xl border border-white/60 bg-white shadow-2xl shadow-slate-900/10 lg:grid-cols-[1.05fr_0.95fr]"
      >
        <aside
          class="relative hidden flex-col justify-between overflow-hidden bg-gradient-to-br from-fluvius-900 via-fluvius-800 to-fluvius-700 p-10 text-emerald-50 lg:flex"
        >
          <div
            class="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-white/10 blur-2xl"
            aria-hidden="true"
          />
          <div
            class="pointer-events-none absolute -bottom-20 left-10 h-64 w-64 rounded-full bg-fluvius-500/30 blur-3xl"
            aria-hidden="true"
          />

          <div class="relative">
            <div class="mb-8 flex items-center gap-3">
              <div class="grid h-11 w-11 place-items-center rounded-xl bg-white font-bold text-fluvius-800 shadow-sm">
                F
              </div>
              <div>
                <p class="text-lg font-semibold tracking-tight text-white">{{ APP_NAME }}</p>
                <p class="text-xs text-emerald-100/70">Atendimento em tempo real</p>
              </div>
            </div>

            <h2 class="max-w-sm text-3xl font-semibold leading-tight tracking-tight text-white">
              Centralize conversas e responda com agilidade.
            </h2>
            <p class="mt-4 max-w-sm text-sm leading-relaxed text-emerald-50/75">
              Receba, assuma e finalize atendimentos em um só lugar — com foco na operação do dia a dia.
            </p>
          </div>

          <ul class="relative mt-10 space-y-3 text-sm text-emerald-50/85">
            <li class="flex items-start gap-3 rounded-xl bg-white/10 px-4 py-3 backdrop-blur-sm">
              <MessageCircle class="mt-0.5 h-4 w-4 shrink-0 text-emerald-200" />
              <span>Inbox unificada para sua equipe de atendimento</span>
            </li>
            <li class="flex items-start gap-3 rounded-xl bg-white/10 px-4 py-3 backdrop-blur-sm">
              <Building2 class="mt-0.5 h-4 w-4 shrink-0 text-emerald-200" />
              <span>Acesso isolado por empresa, com segurança multi-tenant</span>
            </li>
          </ul>

          <p class="relative mt-10 text-xs text-emerald-100/50">v{{ APP_VERSION }}</p>
        </aside>

        <section class="flex flex-col justify-center px-6 py-8 sm:px-10 sm:py-12">
          <div class="mb-8 flex items-center gap-3 lg:hidden">
            <div class="grid h-10 w-10 place-items-center rounded-xl bg-fluvius-900 font-bold text-white shadow-sm">
              F
            </div>
            <div>
              <p class="text-base font-semibold text-slate-900">{{ APP_NAME }}</p>
              <p class="text-xs text-slate-500">Atendimento em tempo real</p>
            </div>
          </div>

          <div class="mb-7">
            <h1 class="text-2xl font-semibold tracking-tight text-slate-900">Entrar</h1>
            <p class="mt-1.5 text-sm text-slate-500">
              Use suas credenciais para acessar os atendimentos.
            </p>
          </div>

          <div
            v-if="tenantLoading"
            class="mb-5 flex items-center gap-2.5 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-3 text-sm text-slate-600"
          >
            <LoaderCircle class="h-4 w-4 animate-spin text-fluvius-600" />
            Validando empresa...
          </div>
          <div
            v-else-if="tenant"
            class="mb-5 flex items-center gap-2.5 rounded-xl border border-fluvius-100 bg-fluvius-50 px-3.5 py-3 text-sm text-fluvius-800"
          >
            <Building2 class="h-4 w-4 shrink-0 text-fluvius-600" />
            <span>
              Acesso exclusivo de <strong class="font-semibold">{{ tenant.name }}</strong>
            </span>
          </div>
          <div
            v-else-if="tenantUnavailable"
            class="mb-5 flex items-start gap-2.5 rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-3 text-sm text-rose-700"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>Empresa indisponível ou link inválido.</span>
          </div>

          <form class="space-y-4" @submit.prevent="submit">
            <div>
              <label for="login-email" class="mb-1.5 block text-sm font-medium text-slate-700">
                E-mail
              </label>
              <div class="relative">
                <Mail
                  class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
                />
                <input
                  id="login-email"
                  v-model="email"
                  type="email"
                  required
                  autocomplete="username"
                  placeholder="voce@empresa.com"
                  :disabled="tenantUnavailable || tenantLoading"
                  class="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-10 pr-3 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-fluvius-600 focus:ring-4 focus:ring-fluvius-600/10 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
                />
              </div>
            </div>

            <div>
              <label for="login-password" class="mb-1.5 block text-sm font-medium text-slate-700">
                Senha
              </label>
              <div class="relative">
                <Lock
                  class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
                />
                <input
                  id="login-password"
                  v-model="password"
                  :type="showPassword ? 'text' : 'password'"
                  required
                  autocomplete="current-password"
                  placeholder="••••••••"
                  :disabled="tenantUnavailable || tenantLoading"
                  class="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-10 pr-11 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-fluvius-600 focus:ring-4 focus:ring-fluvius-600/10 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
                />
                <button
                  type="button"
                  class="absolute right-2 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
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
              class="flex items-start gap-2.5 rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-3 text-sm text-rose-700"
              role="alert"
            >
              <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
              <span>{{ error }}</span>
            </div>

            <button
              type="submit"
              class="mt-2 flex w-full items-center justify-center gap-2 rounded-xl bg-fluvius-600 px-4 py-3 text-sm font-semibold text-white shadow-sm shadow-fluvius-600/25 transition hover:bg-fluvius-700 focus:outline-none focus:ring-4 focus:ring-fluvius-600/20 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!canSubmit"
            >
              <LoaderCircle v-if="auth.loading" class="h-4 w-4 animate-spin" />
              {{ auth.loading ? 'Entrando...' : 'Entrar' }}
            </button>
          </form>

          <p class="mt-8 text-center text-xs text-slate-400 lg:text-left">
            Problemas para entrar? Fale com o administrador da sua empresa.
          </p>
        </section>
      </div>
    </div>
  </div>
</template>
