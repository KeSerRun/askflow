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
            </n-statistic>
            <template #footer>
              <n-text depth="3">管理员: {{ store.dashboardData.admin_count }}</n-text>
            </template>
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
            <template #footer>
              <n-text depth="3">嵌入维度: {{ store.dashboardData.embedding_dim || '-' }}</n-text>
            </template>
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
            <template #footer>
              <n-text depth="3">模型: {{ store.dashboardData.embedding_model || '-' }}</n-text>
            </template>
          </n-card>
        </n-grid-item>
      </n-grid>

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
        <n-grid :cols="4" :x-gap="12" :y-gap="12">
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
                <template v-if="check.latency_ms" #default>
                  <n-text depth="3" style="font-size: 12px">{{ check.latency_ms }}ms</n-text>
                </template>
                <template v-if="check.note" #default>
                  <n-text depth="3" style="font-size: 12px; display: block">{{ check.note }}</n-text>
                </template>
                <template v-if="check.error" #default>
                  <n-ellipsis :line-clamp="2" :tooltip="{ width: 300 }">
                    <n-text type="error" style="font-size: 12px">{{ check.error }}</n-text>
                  </n-ellipsis>
                </template>
              </n-thing>
            </n-card>
          </n-grid-item>
        </n-grid>
      </n-card>

      <!-- 请求统计 + 系统运行信息 -->
      <n-grid :cols="3" :x-gap="16" :y-gap="16" style="margin-top: 16px">
        <n-grid-item :span="1">
          <n-card title="请求统计" :bordered="true" size="small">
            <template v-if="store.dashboardData.request_stats">
              <n-descriptions label-placement="left" :column="1" size="small">
                <n-descriptions-item label="总请求数">
                  {{ store.dashboardData.request_stats.total_requests }}
                </n-descriptions-item>
                <n-descriptions-item label="错误数（4xx/5xx）">
                  <n-text :type="errorCount > 0 ? 'error' : 'default'">
                    {{ store.dashboardData.request_stats.total_errors }}
                  </n-text>
                </n-descriptions-item>
                <n-descriptions-item label="各方法分布">
                  <n-space :size="8">
                    <n-tag v-for="(c, m) in store.dashboardData.request_stats.by_method" :key="m" size="small" :bordered="false">
                      {{ m }}: {{ c }}
                    </n-tag>
                  </n-space>
                </n-descriptions-item>
              </n-descriptions>
            </template>
            <n-empty v-else description="暂无请求统计" />
          </n-card>
        </n-grid-item>
        <n-grid-item :span="2">
          <n-card title="数据分区" :bordered="true" size="small">
            <n-data-table
              v-if="partitionRows.length > 0"
              :columns="partitionColumns"
              :data="partitionRows"
              :bordered="false"
              :single-line="true"
              size="small"
            />
            <n-empty v-else description="暂无分区数据" style="padding: 12px 0" />
          </n-card>
        </n-grid-item>
      </n-grid>

      <!-- 工具调用统计 -->
      <n-card title="工具调用统计" :bordered="true" size="small" style="margin-top: 16px">
        <n-data-table
          v-if="toolCallRows.length > 0"
          :columns="toolCallColumns"
          :data="toolCallRows"
          :bordered="false"
          :single-line="true"
          size="small"
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
import { computed, onMounted } from 'vue'
import { useAdminStore } from '@/stores/admin'
import {
  NCard, NStatistic, NIcon, NText, NGrid, NGridItem,
  NDescriptions, NDescriptionsItem, NTag, NSpace,
  NDataTable, NEmpty, NSpin, NH2, NButton, NEllipsis, NThing,
} from 'naive-ui'
import {
  PeopleOutline, ChatbubblesOutline, DocumentTextOutline, CubeOutline,
  CheckmarkCircleOutline, CloseCircleOutline, RefreshOutline,
} from '@vicons/ionicons5'

const store = useAdminStore()

const errorCount = computed(() => store.dashboardData?.request_stats?.total_errors || 0)

const partitionRows = computed(() => {
  const p = store.dashboardData?.partitions
  if (!p) return []
  return Object.entries(p).map(([name, info]) => ({
    name,
    chunks: info.chunks,
    sources: info.sources,
  }))
})

const partitionColumns = [
  { title: '分区', key: 'name', width: 120 },
  { title: '切块数', key: 'chunks', width: 80 },
  { title: '文档数', key: 'sources', width: 80 },
]

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

async function doHealthCheck() {
  await store.fetchHealth()
}

function loadData() {
  store.fetchDashboard()
}

onMounted(() => {
  loadData()
  store.fetchHealth()  // 独立并行加载，不阻塞仪表盘
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
</style>
