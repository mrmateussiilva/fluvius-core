<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/authStore'

const email = ref('')
const password = ref('')
const route = useRoute()
const error = ref(
  route.query.session === 'expired' ? 'Sua sessão expirou. Entre novamente.' : '',
)
const auth = useAuthStore()
const router = useRouter()

async function submit() {
  error.value = ''
  try {
    await auth.signIn(email.value, password.value)
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
      <button class="w-full rounded-lg bg-fluvius-600 px-4 py-2.5 font-medium text-white hover:bg-fluvius-700 disabled:opacity-50" :disabled="auth.loading">
        {{ auth.loading ? 'Entrando...' : 'Entrar' }}
      </button>
    </form>
  </div>
</template>
