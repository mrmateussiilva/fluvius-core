<script setup lang="ts">
import { Building2, LoaderCircle } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getTenantLogin } from '../api/auth'
import type { TenantLogin } from '../api/auth'
import { useAuthStore } from '../stores/authStore'

const email = ref('')
const password = ref('')
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
  if (tenantUnavailable.value) return
  error.value = ''
  try {
    await auth.signIn(email.value, password.value, tenantSlug.value)
    router.push('/app/conversations')
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : 'Não foi possível entrar'
  }
}
</script>

<template>
  <div class="grid min-h-screen place-items-center bg-slate-100 p-5">
    <form class="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-7 shadow-sm" @submit.prevent="submit">
      <div class="mb-6">
        <h1 class="text-2xl font-bold">Fluvius Core</h1>
        <p class="mt-1 text-sm text-slate-500">Entre para acessar seus atendimentos.</p>
        <div
          v-if="tenantLoading"
          class="mt-4 flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2.5 text-sm text-slate-500"
        >
          <LoaderCircle class="h-4 w-4 animate-spin" />
          Validando empresa...
        </div>
        <div
          v-else-if="tenant"
          class="mt-4 flex items-center gap-2 rounded-lg border border-fluvius-100 bg-fluvius-50 px-3 py-2.5 text-sm text-fluvius-800"
        >
          <Building2 class="h-4 w-4 shrink-0" />
          <span>
            Acesso exclusivo de <strong>{{ tenant.name }}</strong>
          </span>
        </div>
      </div>
      <label class="mb-4 block text-sm font-medium">
        E-mail
        <input v-model="email" type="email" required class="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-fluvius-600" />
      </label>
      <label class="mb-5 block text-sm font-medium">
        Senha
        <input v-model="password" type="password" required class="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-fluvius-600" />
      </label>
      <p v-if="error" class="mb-4 text-sm text-rose-600">{{ error }}</p>
      <button
        class="w-full rounded-lg bg-fluvius-600 px-4 py-2.5 font-medium text-white hover:bg-fluvius-700 disabled:opacity-50"
        :disabled="auth.loading || tenantLoading || tenantUnavailable"
      >
        {{ auth.loading ? 'Entrando...' : 'Entrar' }}
      </button>
    </form>
  </div>
</template>
