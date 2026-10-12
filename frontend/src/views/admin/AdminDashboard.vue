<template>
  <div class="dashboard-page">
    <n-h2>系统总览</n-h2>

    <!-- Loading -->
    <div v-if="store.loading && !store.dashboardData" class="loading-center">
      <n-spin size="large" />
    </div>

    <template v-else-if="store.dashboardData">
      <!-- 统计卡片 -->
      <n-grid :cols="4" :x-gap="16" :y-gap="16" class="stat-grid">
        <n-grid-item>
          <n-card :bordered="true" size="small">
            <n-statistic label="用户总数">
              <template #prefix>
                <n-icon :component="PeopleOutline" style="color:var(--color-primary)" />
              </template>
              <span class="stat-value">{{ store.dashboardData.user_count }}</span>
              <template #suffix>
                <n-text depth="3" style="font-size: 12px; margin-left: 8px">
                  管理员 {{ store.dashboardData.admin_count }}
                </n-text>
              </template>
            </n-statistic>
          </n-card>
        </n-grid-item>
        <n-grid-item>
          <n-card :bordered="true" size="small">
            <n-statistic label="会话总数">
              <template #prefix>
                <n-icon :component="ChatbubblesOutline" style="color:var(--color-primary)" />
              </template>
              <span class="stat-value">{{ store.dashboardData.session_count }}</span>
            </n-statistic>
          </n-card>
        </n-grid-item>
        <n-grid-item>
          <n-card :bordered="true" size="small">
            <n-statistic label="文档总数">
              <template #prefix>
                <n-icon :component="DocumentTextOutline" style="color:var(--color-primary)" />
              </template>
              <span class="stat-value">{{ store.dashboardData.document_count }}</span>
            </n-statistic>
          </n-card>
        </n-grid-item>
        <n-grid-item>
          <n-card :bordered="true" size="small">
            <n-statistic label="切块总数">
              <template #prefix>
                <n-icon :component="CubeOutline" style="color:var(--color-primary)" />
              </template>
              <span class="stat-value">{{ store.dashboardData.chunk_count }}</span>
            </n-statistic>
          </n-card>
        </n-grid-item>
      </n-grid>

      <!-- 服务器资源使用情况 -->
      <n-card :bordered="true" size="small" style="margin-top: 16px">
        <template #header>
          <div class="res-header">
            <span>服务器资源使用情况</span>
            <n-tag v-if="resources?.status" :type="resources.status === 'warning' ? 'warning' : 'success'" size="small" :bordered="false">
              {{ resources.status === 'warning' ? '资源告警' : '正常' }}
            </n-tag>
          </div>
        </template>
        <template #header-extra>
          <n-button size="tiny" :loading="resourcesLoading" :disabled="resourcesLoading" @click="refreshResources">
            <template #icon><n-icon :component="RefreshOutline" /></template>
            刷新
          </n-button>
        </template>

        <n-skeleton v-if="resourcesLoading && !resources" text :repeat="2" />
        <template v-else-if="resources?.available">
          <div class="res-row">
            <div class="res-label">
              <n-icon :component="HardwareChipOutline" /> CPU 使用率
              <n-text depth="3" style="font-size: 12px">{{ resources.cpu.cores }} 核</n-text>
            </div>
            <n-progress type="line" :show-indicator="false" :percentage="roundPct(resources.cpu.percent)" :height="14" :border-radius="4" :color="resColor(resources.cpu.percent)" />
            <n-text class="res-value">{{ resources.cpu.percent }}%</n-text>
          </div>
          <div class="res-row" style="margin-top: 12px">
            <div class="res-label">
              <n-icon :component="ServerOutline" /> RAM 使用率
              <n-text depth="3" style="font-size: 12px">{{ fmtBytes(resources.memory.used) }} / {{ fmtBytes(resources.memory.total) }}</n-text>
            </div>
            <n-progress type="line" :show-indicator="false" :percentage="roundPct(resources.memory.percent)" :height="14" :border-radius="4" :color="resColor(resources.memory.percent)" />
            <n-text class="res-value">{{ resources.memory.percent }}%</n-text>
          </div>
          <n-text v-if="resources.warnings?.length" type="warning" style="font-size: 12px; display: block; margin-top: 8px">
            {{ resources.warnings.join('；') }}
          </n-text>
          <n-text v-if="resources.sampled_at" depth="3" style="font-size: 12px; display: block; margin-top: 4px">
            采样时间 {{ resources.sampled_at }}
          </n-text>
        </template>
        <n-empty v-else-if="resources" :description="resources.reason || '资源信息不可用'" style="padding: 12px 0" />
        <n-text v-else depth="3">加载中…</n-text>
      </n-card>

      <!-- 外部服务状态（前置） -->
      <n-card title="外部服务状态" :bordered="true" size="small" style="margin-top: 16px">
        <template #header-extra>
          <n-button
            size="tiny"
            :loading="store.healthLoading"
            :disabled="store.healthLoading"
            @click="doHealthCheck"
          >
            <template #icon>
              <n-icon :component="RefreshOutline" />
            </template>
            检查
          </n-button>
        </template>
        <n-grid v-if="hasHealth" :cols="3" :x-gap="12" :y-gap="12">
          <n-grid-item v-for="(check, name) in healthChecks" :key="name">
            <n-card :bordered="false" size="tiny" class="health-card">
              <n-thing>
                <template #avatar>
                  <n-icon :size="22" :color="healthColor(check.status)">
                    <component :is="healthIcon(check.status)" />
                  </n-icon>
                </template>
                <template #header>
                  <n-text style="font-weight: 600; text-transform: capitalize">{{ name }}</n-text>
                </template>
                <template #description>
                  <n-text :type="check.status === 'healthy' ? 'success' : 'error'" depth="3" style="font-size: 13px">
                    {{ check.status === 'healthy' ? '正常' : '异常' }}
                  </n-text>
                </template>
                <template #default>
                  <n-text v-if="check.note" depth="3" style="font-size: 12px; display: block">{{ check.note }}</n-text>
                  <n-text v-if="check.latency_ms != null" depth="3" style="font-size: 12px">
                    耗时 {{ check.latency_ms }}ms
                  </n-text>
                  <n-ellipsis v-if="check.error" :line-clamp="2" :tooltip="{ width: 300 }">
                    <n-text type="error" style="font-size: 12px">{{ check.error }}</n-text>
                  </n-ellipsis>
                </template>
              </n-thing>
            </n-card>
          </n-grid-item>
        </n-grid>

        <!-- 未渲染出结果前：始终显示“检查中…”（挂载即触发检查，与「检查」按钮同一逻辑） -->
        <div v-else class="health-placeholder">
          <n-spin v-if="!healthError" size="small" />
          <n-text depth="3" style="margin-left: 8px">{{ healthError || '检查中…' }}</n-text>
          <n-button v-if="healthError" size="tiny" style="margin-left: 8px" @click="doHealthCheck">重试</n-button>
        </div>
      </n-card>

      <!-- 请求统计 -->
      <n-card title="请求统计" :bordered="true" size="small" style="margin-top: 16px">
        <template v-if="rs">
          <n-grid :cols="3" :x-gap="16" :y-gap="8">
            <n-grid-item>
              <n-statistic label="总请求数" :value="rs.total_requests" />
            </n-grid-item>
            <n-grid-item>
              <n-statistic label="错误数（4xx/5xx）" :value="rs.total_errors">
                <template #prefix v-if="errorCount > 0">
                  <n-icon :component="CloseCircleOutline" color="#d03050" />
                </template>
              </n-statistic>
            </n-grid-item>
            <n-grid-item>
              <n-statistic label="有效率" :value="successRateText">
                <template #prefix>
                  <n-icon :component="CheckmarkCircleOutline" color="#18a058" />
                </template>
              </n-statistic>
            </n-grid-item>
          </n-grid>

          <div v-if="methodRows.length" class="method-block">
            <div v-for="row in methodRows" :key="row.method" class="method-row">
              <span class="method-name">{{ row.method }}</span>
              <n-progress type="line" :percentage="row.percent" :show-indicator="false" height="8" class="method-bar" />
              <span class="method-count">{{ row.count }}</span>
            </div>
          </div>
        </template>
        <n-empty v-else description="暂无请求统计" />
      </n-card>

      <!-- 工具调用统计 -->
      <n-card title="工具调用统计" :bordered="true" size="small" style="margin-top: 16px">
        <template #header-extra>
          <n-popconfirm :disabled="!toolCallRows.length" @positive-click="resetToolCounts">
            <template #trigger>
              <n-button size="tiny" quaternary type="error" :disabled="!toolCallRows.length">重置次数</n-button>
            </template>
            确定将所有工具调用次数重置为 0？
          </n-popconfirm>
        </template>
        <n-data-table
          v-if="toolCallRows.length > 0"
          :columns="toolCallColumns"
          :data="toolCallRows"
          :bordered="false"
          :single-line="true"
          size="small"
          :pagination="toolCallPagination"
        />
        <n-empty v-else description="暂无工具调用数据" style="padding: 12px 0" />
      </n-card>
    </template>

    <!-- 无数据 -->
    <n-empty v-else description="点击刷新加载数据" style="margin-top: 60px">
      <template #extra>
        <n-button type="primary" @click="loadData">刷新数据</n-button>
      </template>
    </n-empty>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { useAdminStore } from '@/stores/admin'
import {
  NCard, NStatistic, NIcon, NText, NGrid, NGridItem,
  NDataTable, NEmpty, NSpin, NH2, NButton, NEllipsis, NThing, NProgress, NPopconfirm,
} from 'naive-ui'
import {
  PeopleOutline, ChatbubblesOutline, DocumentTextOutline, CubeOutline,
  CheckmarkCircleOutline, CloseCircleOutline, RefreshOutline,
  HardwareChipOutline, ServerOutline,
} from '@vicons/ionicons5'

const store = useAdminStore()
const message = useMessage()

// ── 服务器资源（CPU / RAM） ──
const resources = computed(() => store.serverResources)
const resourcesLoading = ref(false)
let resTimer = null

function roundPct(v) { return Math.max(0, Math.min(100, Math.round(Number(v) || 0))) }
function resColor(v) {
  const n = Number(v) || 0
  return n > 85 ? '#d03050' : (n > 70 ? '#f0a020' : '#18a058')
}
function fmtBytes(b) {
  const n = Number(b) || 0
  if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(1) + ' GB'
  if (n >= 1024 ** 2) return (n / 1024 ** 2).toFixed(1) + ' MB'
  return Math.round(n / 1024) + ' KB'
}

async function refreshResources() {
  if (resourcesLoading.value) return
  resourcesLoading.value = true
  try {
    await store.fetchServerResources()
  } catch (e) {
    // 存储层已记录 error；首次失败给个空态
    if (!store.serverResources) store.serverResources = { available: false, reason: e.message }
  } finally {
    resourcesLoading.value = false
  }
}

const errorCount = computed(() => store.dashboardData?.request_stats?.total_errors || 0)

const rs = computed(() => store.dashboardData?.request_stats || null)

const successRateText = computed(() => {
  const t = rs.value?.total_requests || 0
  const e = rs.value?.total_errors || 0
  return t ? `${Math.max(0, Math.round((1 - e / t) * 100))}%` : '0%'
})

function methodPct(count) {
  const t = rs.value?.total_requests || 0
  return t ? Math.round((count / t) * 100) : 0
}

const methodRows = computed(() => {
  const by = rs.value?.by_method
  if (!by) return []
  return Object.entries(by)
    .sort((a, b) => b[1] - a[1])
    .map(([m, c]) => ({ method: m, count: c, percent: methodPct(c) }))
})

const dashboardSizeOptions = [10, 20, 50, 100]
const toolCallPagination = reactive({ pageSize: 10, pageSizes: dashboardSizeOptions, showSizePicker: true })

const toolCallColumns = [
  { title: '工具', key: 'name', width: 200 },
  { title: '调用次数', key: 'count', width: 100 },
]

const toolCallRows = computed(() => {
  const counts = store.dashboardData?.tool_call_counts
  if (!counts) return []
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])  // 按调用次数降序
    .map(([name, count]) => ({ name, count }))
})

function healthColor(status) {
  return status === 'healthy' ? '#18a058' : '#d03050'
}

function healthIcon(status) {
  return status === 'healthy' ? CheckmarkCircleOutline : CloseCircleOutline
}

const healthChecks = computed(() => {
  return store.healthData?.checks || store.dashboardData?.health?.checks || {}
})

const hasHealth = computed(() => Object.keys(healthChecks.value).length > 0)
const healthError = ref(null)

async function doHealthCheck() {
  healthError.value = null
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      await store.fetchHealth()
      return
    } catch (e) {
      if (attempt === 0) {
        await new Promise((resolve) => setTimeout(resolve, 800))  // 自动重试一次
      } else {
        healthError.value = e.response?.data?.detail || e.message || '加载失败'
      }
    }
  }
}

function loadData() {
  store.fetchDashboard()
}

// 重置工具调用统计
const resettingToolCounts = ref(false)
async function resetToolCounts() {
  if (resettingToolCounts.value) return
  resettingToolCounts.value = true
  try {
    const res = await store.resetToolCallCounts()
    message.success((res && res.message) || '已重置工具调用次数')
    await loadData()
  } catch (e) {
    message.error(e?.message || '重置失败')
  } finally {
    resettingToolCounts.value = false
  }
}

onMounted(() => {
  loadData()
  // 刷新 = 点击「检查」：挂载即触发同一检查逻辑
  doHealthCheck()
  // 服务器资源：立即拉取 + 每 5 秒自动刷新
  refreshResources()
  resTimer = setInterval(refreshResources, 5000)
})

watch(
  () => store.dashboardData,
  (v) => {
    // 仪表盘数据就绪后，若健康数据仍缺失则再触发一次（兜底读取时序问题）
    if (v && !store.healthData) doHealthCheck()
  },
)

onUnmounted(() => {
  if (resTimer) { clearInterval(resTimer); resTimer = null }
})
</script>

<style scoped>
.dashboard-page {
  width: 100%;
}

.loading-center {
  display: flex;
  justify-content: center;
  padding: 80px 0;
}

.health-placeholder {
  padding: 12px 0;
  display: flex;
  align-items: center;
}

.health-skeleton {
  padding: 8px 0;
}

.stat-grid {
  margin-bottom: 0;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--color-text-1);
}

.path-text {
  font-size: 13px;
  color: var(--color-text-2);
}

.path-count {
  float: right;
  font-weight: 600;
  color: var(--color-primary);
}

.health-card {
  transition: box-shadow 0.2s;
}
.health-card:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
.method-block { margin-top: 16px; border-top: 1px solid var(--color-border); padding-top: 12px; }
.method-row { display: flex; align-items: center; gap: 12px; margin-top: 8px; }
.method-name { width: 70px; font-size: 12px; color: var(--color-text-2); font-weight: 600; }
.method-bar { flex: 1; }
.method-count { width: 48px; text-align: right; font-size: 12px; color: var(--color-text-2); }
.res-row { display: flex; align-items: center; gap: 12px; }
.res-label { display: flex; align-items: center; gap: 6px; width: 300px; font-size: 13px; font-weight: 600; white-space: nowrap; }
.res-value { width: 56px; text-align: right; font-size: 14px; font-weight: 700; color: var(--color-text-1); }
.res-header { display: flex; align-items: center; gap: 10px; }
</style>
