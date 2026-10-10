<template>
  <div class="input-area">
    <div class="input-row">
      <div class="left-actions">
        <!-- 单文件上传 -->
        <n-upload
          :show-file-list="false"
          :custom-request="handleUpload"
          accept=".pdf"
          :disabled="isUploading"
          multiple
        >
          <n-tooltip placement="top">
            <template #trigger>
              <n-button
                circle
                quaternary
                :disabled="isUploading"
              >
                <template #icon>
                  <n-icon :component="AttachOutline" />
                </template>
              </n-button>
            </template>
            上传文件
          </n-tooltip>
        </n-upload>
        <!-- 文件夹上传 -->
        <n-upload
          :show-file-list="false"
          :custom-request="handleUpload"
          accept=".pdf"
          :disabled="isUploading"
          multiple
          directory
        >
          <n-tooltip placement="top">
            <template #trigger>
              <n-button
                circle
                quaternary
                :disabled="isUploading"
              >
                <template #icon>
                  <n-icon :component="FolderOpenOutline" />
                </template>
              </n-button>
            </template>
            上传文件夹
          </n-tooltip>
        </n-upload>
      </div>

      <div class="center-input">
        <n-input
          v-model:value="inputValue"
          type="textarea"
          size="large"
          placeholder="给我发送消息…"
          :autosize="{ minRows: 1, maxRows: 6 }"
          :disabled="isLoading || isUploading"
          @keydown="handleKeydown"
        />
      </div>

      <div class="right-actions">
        <!-- 发送按钮：非 loading 状态 -->
        <n-button
          v-if="!isLoading"
          type="primary"
          size="large"
          circle
          :disabled="!inputValue.trim() || isLoading || isUploading"
          @click="handleSend"
        >
          <template #icon>
            <n-icon :component="ArrowUpOutline" />
          </template>
        </n-button>
        <!-- 停止按钮：loading 状态，中断生成 -->
        <n-button
          v-else
          type="error"
          size="large"
          circle
          @click="$emit('stop')"
        >
          <template #icon>
            <n-icon :component="StopOutline" />
          </template>
        </n-button>
      </div>
    </div>

    <div class="hint">
      <n-text depth="3" style="font-size: 11px">
        按 Enter 发送，Shift + Enter 换行
      </n-text>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import {
  NButton,
  NIcon,
  NInput,
  NUpload,
  NTooltip,
  NText,
} from 'naive-ui'
import { AttachOutline, ArrowUpOutline, FolderOpenOutline, StopOutline } from '@vicons/ionicons5'

const props = defineProps({
  isLoading: { type: Boolean, default: false },
  isUploading: { type: Boolean, default: false },
})

const emit = defineEmits(['send', 'stop', 'upload'])

const inputValue = ref('')

const handleSend = () => {
  const text = inputValue.value.trim()
  if (!text || props.isLoading || props.isUploading) return
  emit('send', text)
  inputValue.value = ''
}

const handleKeydown = (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    handleSend()
  }
}

// custom-request 让我们直接拿到原生 File 对象,转给父组件统一处理
const handleUpload = ({ file, onFinish, onError }) => {
  emit('upload', file.file)
  onFinish()
}
</script>

<style scoped>
.input-area {
  padding: 16px 24px 20px;
  border-top: 1px solid var(--color-border);
  background-color: var(--color-bg-card);
  flex-shrink: 0;
}

.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  width: 100%;
  max-width: 880px;
  margin: 0 auto;
  box-sizing: border-box;
}

/* 左/右按钮:不参与拉伸,贴底对齐 textarea */
.left-actions,
.right-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  padding-bottom: 3px;
}

/* 中间输入框:撑满剩余宽度;min-width:0 必备,否则 textarea 内容会撑破 flex 子项 */
.center-input {
  flex: 1 1 auto;
  min-width: 0;
}

.center-input :deep(.n-input) {
  width: 100%;
}

.hint {
  text-align: center;
  margin-top: 8px;
}

@media (max-width: 768px) {
  .input-area {
    padding: 12px 16px 16px;
  }
}
</style>
