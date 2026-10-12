<template>
  <div class="logs-page">
    <n-h2 style="margin-top: 0">日志管理</n-h2>
    <n-text depth="3" style="font-size: 12px">直接查询数据库日志表（app_logs / request_logs）</n-text>

    <n-tabs type="line" v-model:value="tab" @update:value="onTabChange" style="margin-top: 8px">
      <!-- 应用日志（app_logs 表） -->
      <n-tab-pane name="app" tab="应用日志">
        <n-space justify="space-between" align="center" :wrap="true" style="margin-bottom: 16px">
          <n-space :wrap="true" align="center">
            <n-select v-model:value="appLevel" :options="levelOptions" placeholder="级别" clearable style="width: 140px" @update:value="searchApp" />
            <n-input v-model:value="appKeyword" placeholder="按模块/消息搜索" clearable style="width: 240px" @keydown.enter="searchApp" />
            <n-button type="primary" @click="searchApp">查询</n-button>
          </n-space>
          <n-space align="center">
            <n-button @click="searchApp">刷新</n-button>
            <n-popconfirm @positive-click="clearApp" :positive-button-props="{ type: 'error' }">
              <template #trigger><n-button type="error" secondary>清空</n-button></template>
              确定清空全部应用日志？此操作不可恢复。
            </n-popconfirm>
          </n-space>
        </n-space>
        <n-data-table
          :columns="appColumns" :data="store.appLogsData?.items || []" :loading="loadingApp"
          :bordered="true" :single-line="true" size="small" :row-key="(r) => r.id" :max-height="560"
        />
        <div class="logs-footer">
          <div class="logs-footer-center">
            <n-pagination
              v-model:page="appPage" :page-size="appPageSize" :item-count="store.appLogsData?.total || 0"
              :page-slot="7" show-size-picker :page-sizes="pageSizes"
              @update:page="loadApp" @update:page-size="changeAppSize"
            />
          </div>
          <n-text depth="3" style="font-size: 12px; white-space: nowrap">共 {{ store.appLogsData?.total || 0 }} 条</n-text>
        </div>
      </n-tab-pane>

      <!-- HTTP 调用记录（request_logs 表） -->
      <n-tab-pane name="http" tab="HTTP 调用">
        <n-space justify="space-between" align="center" :wrap="true" style="margin-bottom: 16px">
          <n-space :wrap="true" align="center">
            <n-select v-model:value="httpMethod" :options="methodOptions" placeholder="方法" clearable style="width: 120px" @update:value="searchHttp" />
            <n-input v-model:value="httpUsername" placeholder="用户名" clearable style="width: 160px" @keydown.enter="searchHttp" />
            <n-input v-model:value="httpKeyword" placeholder="按路径搜索" clearable style="width: 240px" @keydown.enter="searchHttp" />
            <n-button type="primary" @click="searchHttp">查询</n-button>
          </n-space>
          <n-space align="center">
            <n-button @click="searchHttp">刷新</n-button>
            <n-popconfirm @positive-click="clearHttp" :positive-button-props="{ type: 'error' }">
              <template #trigger><n-button type="error" secondary>清空</n-button></template>
              确定清空全部 HTTP 调用记录？此操作不可恢复。
            </n-popconfirm>
          </n-space>
        </n-space>
        <n-data-table
          :columns="httpColumns" :data="store.httpLogsData?.items || []" :loading="loadingHttp"
          :bordered="true" :single-line="true" size="small" :row-key="(r) => r.id" :max-height="560"
        />
        <div class="logs-footer">
          <div class="logs-footer-center">
            <n-pagination
              v-model:page="httpPage" :page-size="httpPageSize" :item-count="store.httpLogsData?.total || 0"
              :page-slot="7" show-size-picker :page-sizes="pageSizes"
              @update:page="loadHttp" @update:page-size="changeHttpSize"
            />
          </div>
          <n-text depth="3" style="font-size: 12px; white-space: nowrap">共 {{ store.httpLogsData?.total || 0 }} 条</n-text>
        </div>
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<script setup>
import { h, onMounted, ref } from 'vue'
import {
  NTabs, NTabPane, NButton, NInput, NSelect, NDataTable, NPagination,
  NText, NSpace, NTag, NH2, NIcon, NPopconfirm, useMessage,
} from 'naive-ui'
import { TrashOutline } from '@vicons/ionicons5'
import { useAdminStore } from '@/stores/admin'

const store = useAdminStore()
const message = useMessage()

const tab = ref('app')
const levelOptions = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((l) => ({ label: l, value: l }))
const methodOptions = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'].map((m) => ({ label: m, value: m }))
const pageSizes = [10, 20, 50, 100, 200]

// ── 应用日志（app_logs） ──
const appLevel = ref(null)
const appKeyword = ref('')
const appPage = ref(1)
const appPageSize = ref(20)
const loadingApp = ref(false)

async function loadApp() {
  loadingApp.value = true
  try {
    await store.fetchAppLogs({
      page: appPage.value,
      page_size: appPageSize.value,
      level: appLevel.value || undefined,
      keyword: appKeyword.value || undefined,
    })
  } catch (e) { message.error(e.message) }
  finally { loadingApp.value = false }
}
function searchApp() { appPage.value = 1; loadApp() }
function changeAppSize(size) { appPageSize.value = size; appPage.value = 1; loadApp() }

async function removeAppLog(id) {
  try {
    await store.deleteAppLog(id)
    message.success('已删除')
    loadApp()
  } catch (e) { message.error(e.message) }
}

async function clearApp() {
  try {
    const r = await store.clearAppLogs()
    message.success(`已清空 ${r.deleted || 0} 条应用日志`)
    loadApp()
  } catch (e) { message.error(e.message) }
}

const appColumns = [
  { title: '时间', key: 'created_at', width: 190 },
  {
    title: '级别', key: 'level', width: 90,
    render: (r) => h(NTag, {
      size: 'small', bordered: false,
      type: (r.level === 'ERROR' || r.level === 'CRITICAL') ? 'error' : r.level === 'WARNING' ? 'warning' : r.level === 'DEBUG' ? 'default' : 'info',
    }, { default: () => r.level }),
  },
  { title: '模块', key: 'module', width: 140 },
  { title: '行', key: 'lineno', width: 60 },
  { title: '消息', key: 'message', ellipsis: { tooltip: true } },
  {
    title: '操作', key: 'actions', width: 60,
    render: (r) => h(NPopconfirm,
      { onPositiveClick: () => removeAppLog(r.id) },
      {
        trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error' }, { icon: () => h(NIcon, { component: TrashOutline }) }),
        default: () => '删除该条日志？',
      }),
  },
]

// ── HTTP 调用记录（request_logs） ──
const httpMethod = ref(null)
const httpUsername = ref('')
const httpKeyword = ref('')
const httpPage = ref(1)
const httpPageSize = ref(20)
const loadingHttp = ref(false)

async function loadHttp() {
  loadingHttp.value = true
  try {
    await store.fetchHttpLogs({
      page: httpPage.value,
      page_size: httpPageSize.value,
      method: httpMethod.value || undefined,
      username: httpUsername.value || undefined,
      keyword: httpKeyword.value || undefined,
    })
  } catch (e) { message.error(e.message) }
  finally { loadingHttp.value = false }
}
function searchHttp() { httpPage.value = 1; loadHttp() }
function changeHttpSize(size) { httpPageSize.value = size; httpPage.value = 1; loadHttp() }

async function removeHttpLog(id) {
  try {
    await store.deleteHttpLog(id)
    message.success('已删除')
    loadHttp()
  } catch (e) { message.error(e.message) }
}

async function clearHttp() {
  try {
    const r = await store.clearHttpLogs()
    message.success(`已清空 ${r.deleted || 0} 条 HTTP 记录`)
    loadHttp()
  } catch (e) { message.error(e.message) }
}

const httpColumns = [
  { title: '时间', key: 'created_at', width: 190 },
  { title: '方法', key: 'method', width: 90, render: (r) => h(NTag, { size: 'small', bordered: false, type: 'primary' }, { default: () => r.method }) },
  { title: '路径', key: 'path', ellipsis: { tooltip: true } },
  {
    title: '状态', key: 'status_code', width: 80,
    render: (r) => h(NTag, { size: 'small', bordered: false, type: r.is_error ? 'error' : 'success' }, { default: () => r.status_code }),
  },
  { title: '用户', key: 'username', width: 110 },
  { title: '耗时(ms)', key: 'latency_ms', width: 100 },
  {
    title: '操作', key: 'actions', width: 60,
    render: (r) => h(NPopconfirm,
      { onPositiveClick: () => removeHttpLog(r.id) },
      {
        trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error' }, { icon: () => h(NIcon, { component: TrashOutline }) }),
        default: () => '删除该条记录？',
      }),
  },
]

function onTabChange(value) {
  if (value === 'app') loadApp()
  else if (value === 'http') loadHttp()
}

onMounted(loadApp)
</script>

<style scoped>
.logs-page { padding: 4px; }

/* 底部：分页居中，共X条靠右下角 */
.logs-footer {
  display: flex;
  align-items: center;
  margin-top: 16px;
  gap: 12px;
}
.logs-footer-center {
  flex: 1;
  display: flex;
  justify-content: center;
  min-width: 0;
}
</style>