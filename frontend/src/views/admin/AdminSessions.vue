<template>
  <div class="sessions-page">
    <n-card :bordered="true" size="small">
      <n-space style="margin-bottom: 16px" :wrap="true">
        <n-input v-model:value="fKeyword" placeholder="按用户名 / 会话ID 搜索" clearable style="width: 260px" @keydown.enter="search" />
        <n-button type="primary" @click="search">
          <template #icon><n-icon :component="SearchOutline" /></template>搜索
        </n-button>
        <n-button @click="reset">重置</n-button>
      </n-space>

      <n-data-table
        :columns="columns" :data="store.sessionsData?.items || []" :loading="store.loading"
        :bordered="true" :single-line="true" size="small" :row-key="(r) => r.session_id"
      />
      <n-space justify="center" style="margin-top: 16px">
        <n-pagination
          v-model:page="page" :page-size="pageSize" :item-count="store.sessionsData?.total || 0"
          :page-slot="7" show-size-picker :page-sizes="pageSizes"
          @update:page="load" @update:page-size="changeSize"
        />
        <n-text depth="3" style="font-size: 12px; line-height: 32px">共 {{ store.sessionsData?.total || 0 }} 条</n-text>
      </n-space>
    </n-card>

    <!-- 历史弹窗 -->
    <n-modal v-model:show="showHistory" preset="card" title="会话历史" style="width: 620px">
      <template v-if="historyLoading">
        <div style="text-align: center; padding: 30px"><n-spin /></div>
      </template>
      <div v-else-if="historyList.length" style="max-height: 60vh; overflow: auto">
        <n-card v-for="(e, i) in historyList" :key="i" size="small" :bordered="true" style="margin-bottom: 8px">
          <n-text depth="3" style="font-size: 12px">{{ e.type }} · {{ e.timestamp }}</n-text>
          <template v-if="e.user != null">
            <br /><n-text><b>用户：</b>{{ e.user }}</n-text>
            <br /><n-text><b>助手：</b>{{ e.assistant }}</n-text>
          </template>
          <template v-else-if="e.messages">
            <div v-for="(m, mi) in e.messages" :key="mi">
              <n-text :type="m.role === 'user' ? 'default' : 'success'"><b>{{ m.role }}：</b>{{ m.content }}</n-text>
            </div>
          </template>
          <template v-else-if="e.event_type">
            <n-text>{{ e.event_type }} {{ (e.files || []).join(', ') }}</n-text>
          </template>
        </n-card>
      </div>
      <n-empty v-else description="无历史记录" />
    </n-modal>
  </div>
</template>

<script setup>
import { h, onMounted, ref } from 'vue'
import {
  NCard, NDataTable, NInput, NButton, NSpace, NPagination, NText,
  NModal, NSpin, NEmpty, NIcon, NPopconfirm, useMessage,
} from 'naive-ui'
import { SearchOutline, EyeOutline, TrashOutline, RefreshOutline } from '@vicons/ionicons5'
import { useAdminStore } from '@/stores/admin'

const store = useAdminStore()
const message = useMessage()

const page = ref(1)
const pageSize = ref(20)
const pageSizes = [10, 20, 50, 100, 200]
const fKeyword = ref('')

async function load() {
  try {
    await store.fetchSessions({
      page: page.value,
      page_size: pageSize.value,
      keyword: fKeyword.value || undefined,
    })
  } catch (e) { message.error(e.message) }
}
function changeSize(size) {
  pageSize.value = size
  page.value = 1
  load()
}
function search() { page.value = 1; load() }
function reset() { fKeyword.value = ''; page.value = 1; load() }

const showHistory = ref(false)
const historyLoading = ref(false)
const historyList = ref([])
async function openHistory(session_id) {
  showHistory.value = true
  historyLoading.value = true
  try { historyList.value = await store.fetchSessionHistory(session_id) }
  catch (e) { message.error(e.message); historyList.value = [] }
  finally { historyLoading.value = false }
}
async function clearHistory(row) {
  try { await store.clearSessionHistory(row.session_id); message.success('历史已清空'); load() }
  catch (e) { message.error(e.message) }
}
async function remove(row) {
  try { await store.deleteSessionAdmin(row.session_id); message.success('已删除'); load() }
  catch (e) { message.error(e.message) }
}

const columns = [
  { title: '会话ID', key: 'session_id', ellipsis: { tooltip: true }, minWidth: 220 },
  { title: '用户', key: 'username', width: 120 },
  { title: '创建时间', key: 'created_at', width: 180 },
  { title: '历史条数', key: 'history_count', width: 90 },
  { title: '首条消息', key: 'first_msg', ellipsis: { tooltip: true }, minWidth: 160 },
  {
    title: '操作', key: 'actions', width: 200,
    render: (row) => h(NSpace, { size: 4 }, [
      h(NButton, { size: 'tiny', quaternary: true, onClick: () => openHistory(row.session_id) },
        { icon: () => h(NIcon, { component: EyeOutline }), default: () => '历史' }),
      h(NPopconfirm, { onPositiveClick: () => clearHistory(row) },
        { trigger: () => h(NButton, { size: 'tiny', quaternary: true },
            { icon: () => h(NIcon, { component: RefreshOutline }), default: () => '清空' }),
          default: () => `清空会话 ${row.session_id} 的历史？` }),
      h(NPopconfirm, { onPositiveClick: () => remove(row) },
        { trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error' },
            { icon: () => h(NIcon, { component: TrashOutline }), default: () => '删除' }),
          default: () => `删除会话 ${row.session_id}？` }),
    ]),
  },
]

onMounted(load)
</script>