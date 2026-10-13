<template>
  <div class="settings-page">
    <n-h2>系统设置</n-h2>
    <n-text depth="3" style="display:block; margin-bottom: 20px">
      配置保存到数据库（动态生效，覆盖 .env）；按分组展示，敏感字段已脱敏。
    </n-text>

    <div v-if="store.loading && !store.configData" class="loading-center">
      <n-spin size="large" />
    </div>

    <template v-else-if="store.configData">
      <n-card v-for="group in groups" :key="group" :title="group" :bordered="true" size="small" style="margin-bottom: 16px">
        <n-form label-placement="left" label-width="180" size="small">
          <n-form-item v-for="field in fieldsByGroup(group)" :key="field.key" :label="field.label">
            <!-- 多行文本（优先于 string，避免 textarea=true 被 type=string 拦截） -->
            <n-input v-if="field.textarea" v-model:value="form[field.key]" type="textarea" :rows="3" :placeholder="field.placeholder || ''" />
            <!-- 字符串输入 -->
            <n-input v-else-if="field.type === 'string'" v-model:value="form[field.key]" :placeholder="field.placeholder || ''" />
            <!-- 密码输入 -->
            <n-input v-else-if="field.type === 'password'" v-model:value="form[field.key]" type="password" show-password-on="click" :placeholder="field.placeholder || ''" />
            <!-- 整数 -->
            <n-input-number v-else-if="field.type === 'int'" v-model:value="form[field.key]" :min="field.min" :max="field.max" style="width:140px" />
            <!-- 浮点数 -->
            <n-input-number v-else-if="field.type === 'float'" v-model:value="form[field.key]" :min="field.min" :max="field.max" :step="field.step || 0.1" style="width:140px" />
            <!-- 开关 -->
            <n-switch v-else-if="field.type === 'bool'" v-model:value="form[field.key]" />
            <!-- 下拉选择 -->
            <n-select v-else-if="field.type === 'select'" v-model:value="form[field.key]" :options="field.options" style="width:200px" clearable />
          </n-form-item>
        </n-form>
      </n-card>

      <n-space style="margin-top: 20px">
        <n-button type="primary" :loading="store.loading" @click="handleSave">保存设置</n-button>
        <n-button @click="handleReset">重置</n-button>
      </n-space>
    </template>

    <n-empty v-else description="暂无配置数据" style="margin-top: 60px">
      <template #extra>
        <n-button type="primary" @click="loadData">加载配置</n-button>
      </template>
    </n-empty>
  </div>
</template>

<script setup>
import { computed, reactive, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { useAdminStore } from '@/stores/admin'
import {
  NButton, NCard, NForm, NFormItem, NInput, NInputNumber,
  NSelect, NSwitch, NText, NSpace, NEmpty, NSpin, NH2,
} from 'naive-ui'

const store = useAdminStore()
const message = useMessage()

const form = reactive({})

const groups = computed(() => {
  const gs = new Set()
  for (const f of store.configSchema) {
    if (f.group) gs.add(f.group)
  }
  return [...gs]
})

function fieldsByGroup(group) {
  return store.configSchema.filter(f => f.group === group)
}

function applyConfig(data) {
  if (!data) return
  for (const field of store.configSchema) {
    const key = field.key
    if (key in data) {
      let val = data[key]
      // 列表类型（如 stop_words）转逗号分隔字符串，让文本输入框正确显示
      if (Array.isArray(val)) {
        val = val.join(', ')
      }
      form[key] = val
    }
  }
}

async function loadData() {
  await store.fetchConfigSchema()
  const data = await store.fetchConfig()
  applyConfig(data)
}

function handleSave() {
  const updates = { ...form }
  store.updateConfig(updates)
    .then(() => message.success('配置已更新'))
    .catch(e => message.error(e.response?.data?.detail || '保存失败'))
}

function handleReset() {
  applyConfig(store.configData)
  message.info('已重置为当前配置')
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.settings-page {
  max-width: 1200px;
}
.loading-center {
  display: flex;
  justify-content: center;
  padding: 80px 0;
}
</style>
