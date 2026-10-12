<template>
  <n-modal
    :show="isOpen"
    preset="card"
    :bordered="false"
    title="会话附件"
    style="max-width: 600px; width: 94vw"
    :mask-closable="true"
    :segmented="{ content: false, footer: 'soft' }"
    @update:show="(v) => !v && $emit('close')"
  >
    <template #header-extra>
      <n-space align="center" :size="12">
        <n-text depth="3">{{ filteredDocs.length }} 个附件</n-text>
        <n-button size="small" quaternary circle @click="$emit('refresh')" title="刷新">
          <template #icon>
            <n-icon :component="RefreshOutline" />
          </template>
        </n-button>
      </n-space>
    </template>

    <div class="modal-body">
      <!-- 搜索栏 -->
      <div class="search-row">
        <n-input
          v-model:value="searchQuery"
          placeholder="搜索附件…"
          clearable
          round
          size="small"
        >
          <template #prefix>
            <n-icon :component="SearchOutline" />
          </template>
        </n-input>
      </div>

      <!-- 存储用量 -->
      <div v-if="storageLimitEnabled" class="storage-bar">
        <n-progress
          :percentage="storagePercent"
          :indicator-placement="'inside'"
          :color="storageBarColor"
          :height="18"
          :border-radius="4"
        >
          {{ storageText }}
        </n-progress>
      </div>

      <n-empty
        v-if="filteredDocs.length === 0"
        :description="documents.length === 0 ? '还没有上传任何附件' : '没有匹配的附件'"
        style="margin: 24px 0"
      >
        <template #extra>
          <n-text depth="3" v-if="documents.length === 0">在对话区底部使用上传按钮添加</n-text>
        </template>
      </n-empty>

      <n-scrollbar v-else style="max-height: 44vh">
        <n-checkbox-group v-model:value="selected">
          <div class="doc-list">
            <label
              v-for="docName in pagedDocs"
              :key="docName"
              class="doc-item"
              :class="{ checked: selected.includes(docName) }"
              title="双击打开 / 下载"
              @dblclick.prevent="$emit('open', docName)"
            >
              <n-checkbox :value="docName" />
              <n-icon
                :size="20"
                :component="DocumentTextOutline"
                style="color: var(--color-primary); margin-left: 4px"
              />
              <span class="doc-name">{{ docName }}</span>
              <n-tag
                v-if="parseInfo(docName)"
                :type="parseInfo(docName).tag"
                :title="parseInfo(docName).error || ''"
                size="small"
                :bordered="false"
              >
                {{ parseInfo(docName).text }}
              </n-tag>
            </label>
          </div>
        </n-checkbox-group>
      </n-scrollbar>

      <!-- 分页器 -->
      <div v-if="totalPages > 1" class="pagination-row">
        <n-pagination
          :page="currentPage"
          :page-count="totalPages"
          :page-size="pageSize"
          size="small"
          show-size-picker
          :page-sizes="pageSizes"
          @update:page="currentPage = $event"
          @update:page-size="onSizeChange"
        />
      </div>
    </div>

    <template #footer>
      <div class="footer">
        <n-text depth="3">已选择 <b>{{ selected.length }}</b> 个</n-text>
        <n-space>
          <n-button @click="$emit('close')">取消</n-button>
          <n-button
            type="error"
            :disabled="selected.length === 0 || isDeleting"
            :loading="isDeleting"
            @click="handleDelete"
          >
            <template #icon>
              <n-icon :component="TrashOutline" />
            </template>
            删除选中
          </n-button>
        </n-space>
      </div>
    </template>
  </n-modal>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import {
  NModal,
  NCheckbox,
  NCheckboxGroup,
  NButton,
  NIcon,
  NInput,
  NEmpty,
  NScrollbar,
  NSpace,
  NText,
  NPagination,
  NProgress,
  NTag,
} from 'naive-ui'
import { DocumentTextOutline, TrashOutline, SearchOutline, RefreshOutline } from '@vicons/ionicons5'

const props = defineProps({
  isOpen: { type: Boolean, default: false },
  documents: { type: Array, required: true },
  storage: { type: Object, default: () => ({ current_mb: 0, max_mb: 0, limit_enabled: false }) },
  isDeleting: { type: Boolean, default: false },
  parseStatus: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['close', 'delete', 'open', 'refresh'])

// 附件 MinerU 解析状态（由父组件轮询传入：{name: {status, error}}）
const _PARSE_UI = {
  pending: { text: '待解析', tag: 'info' },
  parsing: { text: '解析中', tag: 'warning' },
  success: { text: '已解析', tag: 'success' },
  failed: { text: '解析失败', tag: 'error' },
  skipped: { text: '未解析', tag: 'default' },
}
const parseInfo = (name) => {
  const s = props.parseStatus?.[name]
  if (!s) return null
  const ui = _PARSE_UI[s.status]
  return ui ? { ...ui, error: s.error || '' } : null
}

const selected = ref([])
const searchQuery = ref('')
const currentPage = ref(1)
const pageSize = ref(10)
const pageSizes = [10, 20, 50, 100]

// 存储用量（由父组件传入：当前会话暂存用量）
const storageLimitEnabled = computed(() => !!props.storage?.limit_enabled)

const storagePercent = computed(() => {
  if (!props.storage?.max_mb) return 0
  return Math.min(100, Math.round((props.storage.current_mb / props.storage.max_mb) * 100))
})

const storageText = computed(() => {
  return `${(props.storage?.current_mb || 0).toFixed(1)}MB / ${props.storage?.max_mb || 0}MB`
})

const storageBarColor = computed(() => {
  if (storagePercent.value >= 90) return 'var(--color-danger)'
  if (storagePercent.value >= 70) return 'var(--color-warning-alt)'
  return 'var(--color-primary)'
})

// 搜索过滤
const filteredDocs = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return props.documents
  return props.documents.filter((name) => name.toLowerCase().includes(q))
})

// 分页
const totalPages = computed(() => Math.ceil(filteredDocs.value.length / pageSize.value) || 0)

const pagedDocs = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredDocs.value.slice(start, start + pageSize.value)
})

function onSizeChange(size) {
  pageSize.value = size
  currentPage.value = 1
}

// 搜索或文档变化时回到第一页
watch([searchQuery, () => props.documents], () => {
  currentPage.value = 1
})

// 弹窗打开时重置
watch(
  () => props.isOpen,
  (open) => {
    if (open) {
      selected.value = []
      searchQuery.value = ''
      currentPage.value = 1
    }
  }
)

const handleDelete = () => {
  if (selected.value.length === 0) return
  emit('delete', [...selected.value])
}
</script>

<style scoped>
.modal-body {
  min-height: 100px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.search-row {
  padding: 0 2px;
}

.doc-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 0;
}

.doc-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  cursor: pointer;
  transition: all 0.15s ease;
  background-color: transparent;
}

.doc-item:hover {
  border-color: var(--color-primary);
  background-color: var(--color-primary-bg-hover);
}

.doc-item.checked {
  border-color: var(--color-primary);
  background-color: var(--color-primary-bg-active);
}

.doc-name {
  flex: 1;
  font-size: 14px;
  color: var(--color-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pagination-row {
  display: flex;
  justify-content: center;
  padding-top: 4px;
}

.storage-bar {
  margin: 0 2px;
}

.footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
