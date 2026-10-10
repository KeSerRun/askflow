<template>
  <n-modal
    :show="isOpen"
    preset="card"
    :bordered="false"
    title="知识库文档"
    style="max-width: 600px; width: 94vw"
    :mask-closable="true"
    :segmented="{ content: false, footer: 'soft' }"
    @update:show="(v) => !v && $emit('close')"
  >
    <template #header-extra>
      <n-space align="center" :size="12">
        <n-text depth="3">{{ filteredDocs.length }} 个文档</n-text>
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
          placeholder="搜索文档…"
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
        :description="documents.length === 0 ? '还没有上传任何文档' : '没有匹配的文档'"
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
          @update:page="currentPage = $event"
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
import { ref, computed, watch, onMounted } from 'vue'
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
} from 'naive-ui'
import { DocumentTextOutline, TrashOutline, SearchOutline, RefreshOutline } from '@vicons/ionicons5'
import axios from '@/http/interceptor'

const props = defineProps({
  isOpen: { type: Boolean, default: false },
  documents: { type: Array, required: true },
  isDeleting: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'delete', 'open', 'refresh'])

const selected = ref([])
const searchQuery = ref('')
const currentPage = ref(1)
const pageSize = 10

// 存储用量
const storageCurrent = ref(0)
const storageMax = ref(0)
const storageLimitEnabled = ref(false)

const storagePercent = computed(() => {
  if (!storageMax.value) return 0
  return Math.min(100, Math.round((storageCurrent.value / storageMax.value) * 100))
})

const storageText = computed(() => {
  return `${storageCurrent.value.toFixed(1)}MB / ${storageMax.value}MB`
})

const storageBarColor = computed(() => {
  if (storagePercent.value >= 90) return 'var(--color-danger)'
  if (storagePercent.value >= 70) return 'var(--color-warning-alt)'
  return 'var(--color-primary)'
})

async function fetchStorageInfo() {
  try {
    const res = await axios.get('/api/documents/storage/info')
    if (res.data.limit_enabled) {
      storageCurrent.value = res.data.current_mb
      storageMax.value = res.data.max_mb
      storageLimitEnabled.value = true
    } else {
      storageLimitEnabled.value = false
    }
  } catch {
    storageLimitEnabled.value = false
  }
}

// 搜索过滤
const filteredDocs = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return props.documents
  return props.documents.filter((name) => name.toLowerCase().includes(q))
})

// 分页
const totalPages = computed(() => Math.ceil(filteredDocs.value.length / pageSize) || 0)

const pagedDocs = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredDocs.value.slice(start, start + pageSize)
})

// 搜索或文档变化时回到第一页，并刷新存储容量
watch([searchQuery, () => props.documents], () => {
  currentPage.value = 1
  if (props.isOpen) {
    fetchStorageInfo()
  }
})

// 弹窗打开时重置
watch(
  () => props.isOpen,
  (open) => {
    if (open) {
      selected.value = []
      searchQuery.value = ''
      currentPage.value = 1
      fetchStorageInfo()
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
