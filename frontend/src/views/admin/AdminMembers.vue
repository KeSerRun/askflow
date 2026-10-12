<template>
  <div class="members-page">
    <n-h2 style="margin-top: 0">用户与会话</n-h2>
    <n-tabs type="line" v-model:value="tab">
      <n-tab-pane name="users" tab="用户管理">
        <AdminUsers />
      </n-tab-pane>
      <n-tab-pane name="sessions" tab="会话管理">
        <AdminSessions />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { NH2, NTabs, NTabPane } from 'naive-ui'
import { useRoute, useRouter } from 'vue-router'
import AdminUsers from './AdminUsers.vue'
import AdminSessions from './AdminSessions.vue'

const route = useRoute()
const router = useRouter()
const tab = ref(route.query.tab === 'sessions' ? 'sessions' : 'users')

// 选中变化同步到 URL（便于共享访问旧 /admin/sessions、/admin/users 的链接）
watch(tab, (v) => router.replace({ query: { tab: v } }))

onMounted(() => {
  if (route.query.tab) tab.value = route.query.tab
})
</script>

<style scoped>
.members-page { width: 100%; }
</style>