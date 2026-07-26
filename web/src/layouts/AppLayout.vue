<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { LogOut, MessageCircle, Settings, UserRoundCog, Zap } from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/authStore'
import { useRealtimeStore } from '../stores/realtimeStore'

const auth = useAuthStore()
const realtime = useRealtimeStore()
const router = useRouter()
const userInitial = computed(() => auth.user?.name?.trim().charAt(0).toUpperCase() || 'U')

onMounted(() => {
  void auth.restore().catch(() => undefined)
})

function logout() {
  realtime.disconnect()
  auth.signOut()
  router.push('/login')
}
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-[#e9edef]">
    <nav class="flex w-[68px] shrink-0 flex-col items-center bg-fluvius-900 py-4 text-emerald-50/70 shadow-xl shadow-slate-900/10">
      <div class="mb-7 grid h-10 w-10 place-items-center rounded-xl bg-white font-bold text-fluvius-800 shadow-sm" title="Fluvius Core">
        F
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
        class="mb-1.5 rounded-xl p-3 transition hover:bg-white/10 hover:text-white"
        active-class="bg-white/15 text-white shadow-sm"
        to="/app/quick-replies"
        title="Respostas rápidas"
      >
        <Zap class="h-5 w-5" />
      </RouterLink>
      <RouterLink
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
