<template>
  <div class="deliverables-page">
    <n-h2>交付物模板</n-h2>
    <n-text depth="3" class="page-hint">
      维护 HTML 模板（Jinja2）—— 模型调用 create_deliverable 时用所选模板 + 内容渲染成 PDF 交付物。
      文本字段加 <code>| md</code> 过滤器即可渲染 <b>Markdown</b>（标题 / 列表 / 加粗 / 表格）；可用样例内容预览。
    </n-text>

    <div class="layout">
      <!-- 模板列表 -->
      <n-card size="small" title="模板列表" class="side">
        <template #header-extra>
          <n-space :size="6">
            <n-popconfirm @positive-click="resetBuiltins">
              <template #trigger>
                <n-button size="tiny" :loading="resetting">重置内置</n-button>
              </template>
              用代码内置版本覆盖三套内置模板？（对内置模板的人工改动会丢失）
            </n-popconfirm>
            <n-button size="tiny" type="primary" secondary @click="startNew">新增</n-button>
          </n-space>
        </template>
        <div v-if="templates.length" class="tpl-list">
          <div
            v-for="t in templates" :key="t.name"
            class="tpl-item" :class="{ active: t.name === selected && !isNew }"
            @click="openTemplate(t.name)"
          >
            <div class="tpl-label">{{ t.label || t.name }}</div>
            <div class="tpl-name">{{ t.name }}</div>
          </div>
        </div>
        <n-empty v-else description="暂无模板" style="margin: 20px 0" />
      </n-card>

      <!-- 编辑器 -->
      <n-card size="small" :title="isNew ? '新增模板' : `编辑模板：${selected || '—'}`" class="editor">
        <n-form label-placement="top" size="small">
          <n-form-item label="模板标识（template，工具入参；仅字母/数字/下划线/连字符）">
            <n-input v-model:value="form.name" :disabled="!isNew" placeholder="research_report" />
          </n-form-item>
          <n-form-item label="显示名（label）">
            <n-input v-model:value="form.label" placeholder="研究报告" />
          </n-form-item>
          <n-form-item label="用途说明（description，供模型选择模板时参考）">
            <n-input v-model:value="form.description" type="textarea" :rows="2" />
          </n-form-item>
          <n-form-item label="内容字段（fields，JSON：供模型按结构填写 content）">
            <n-input v-model:value="form.fieldsText" type="textarea" :rows="4" placeholder='[{"key":"summary","label":"摘要","type":"text"}]' />
          </n-form-item>
          <n-form-item label="主题色（accent：强调条 / 章节标题 / 表头底色；留空用品牌主色）">
            <n-color-picker v-model:value="form.accent" :show-alpha="false" :modes="['hex']" style="width: 160px" />
          </n-form-item>
          <n-form-item label="模板 HTML（Jinja2：标题用 title、日期用 today、内容用 content.* ；文本字段加 | md 渲染 Markdown）">
            <n-input v-model:value="form.html" type="textarea" :rows="14" class="code-area" />
          </n-form-item>
          <n-form-item label="自定义 CSS（可选，追加在默认样式之后，可覆盖：字号 / 颜色 / 边距 / 表格等）">
            <n-input v-model:value="form.css" type="textarea" :rows="5" class="code-area" />
          </n-form-item>
        </n-form>

        <template #footer>
          <n-space justify="space-between">
            <n-popconfirm v-if="!isNew && selected" @positive-click="removeTemplate">
              <template #trigger>
                <n-button size="small" type="error" quaternary :disabled="saving">删除</n-button>
              </template>
              确定删除模板「{{ selected }}」？
            </n-popconfirm>
            <span v-else />
            <n-space>
              <n-button size="small" :disabled="!canPreview || saving" @click="doPreview">预览 PDF</n-button>
              <n-button size="small" type="primary" :loading="saving" :disabled="!canSave" @click="doSave">保存</n-button>
            </n-space>
          </n-space>
        </template>
      </n-card>
    </div>

    <!-- PDF 预览（页内模态 + iframe，避免弹窗拦截） -->
    <n-modal
      v-model:show="previewVisible"
      preset="card"
      :title="`PDF 预览：${previewName}`"
      style="width: 920px"
    >
      <iframe v-if="previewUrl" :src="previewUrl" class="preview-frame" title="PDF 预览" />
    </n-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import {
  NButton,
  NCard,
  NColorPicker,
  NEmpty,
  NForm,
  NFormItem,
  NH2,
  NInput,
  NModal,
  NPopconfirm,
  NSpace,
  NText,
  useMessage,
} from 'naive-ui'
import { useAdminStore } from '@/stores/admin'

const store = useAdminStore()
const message = useMessage()

const templates = computed(() => store.deliverableTemplates)
const selected = ref('')
const isNew = ref(false)
const saving = ref(false)
const resetting = ref(false)
const form = reactive({ name: '', label: '', description: '', accent: '', css: '', fieldsText: '[]', html: '' })

const canSave = computed(() => !!form.name.trim() && !!form.html.trim() && !saving.value)
const canPreview = computed(() => !isNew.value && !!selected.value)

function applyTemplate(data) {
  form.name = data.name || ''
  form.label = data.label || ''
  form.description = data.description || ''
  form.accent = data.accent || ''
  form.css = data.css || ''
  form.fieldsText = JSON.stringify(data.fields || [], null, 2)
  form.html = data.html || ''
}

async function loadList() {
  await store.fetchDeliverableTemplates()
}

async function openTemplate(name) {
  try {
    const data = await store.fetchDeliverableTemplate(name)
    selected.value = name
    isNew.value = false
    applyTemplate(data)
  } catch (e) {
    message.error(e?.response?.data?.detail || '读取模板失败')
  }
}

function startNew() {
  selected.value = ''
  isNew.value = true
  applyTemplate({
    name: '',
    label: '',
    accent: '',
    css: '',
    fields: [],
    html: [
      '<div class="hero">',
      '  <div class="kicker">文档类型 · {{ today }}</div>',
      '  <h1>{{ title }}</h1>',
      '</div>',
      '{% if content.summary %}<h2>摘要</h2>{{ content.summary | md }}{% endif %}',
      '',
    ].join('\n'),
  })
}

function parseFields() {
  try {
    const v = JSON.parse(form.fieldsText || '[]')
    return Array.isArray(v) ? v : []
  } catch {
    throw new Error('fields 不是合法 JSON')
  }
}

async function doSave() {
  saving.value = true
  try {
    let fields
    try {
      fields = parseFields()
    } catch (e) {
      message.error(e.message)
      return
    }
    await store.saveDeliverableTemplate(form.name.trim(), {
      label: form.label,
      description: form.description,
      accent: form.accent,
      css: form.css,
      fields,
      html: form.html,
    })
    message.success('模板已保存')
    selected.value = form.name.trim()
    isNew.value = false
  } catch (e) {
    message.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function removeTemplate() {
  try {
    await store.deleteDeliverableTemplate(selected.value)
    message.success('模板已删除')
    selected.value = ''
    isNew.value = false
    form.name = ''; form.label = ''; form.description = ''; form.accent = ''; form.css = ''
    form.fieldsText = '[]'; form.html = ''
  } catch (e) {
    message.error(e?.response?.data?.detail || '删除失败')
  }
}

const previewVisible = ref(false)
const previewUrl = ref('')
const previewName = ref('')

async function doPreview() {
  if (!canPreview.value) return
  try {
    const blob = await store.previewDeliverableTemplate(selected.value)
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = URL.createObjectURL(blob)
    previewName.value = selected.value
    previewVisible.value = true
  } catch (e) {
    message.error('预览失败')
  }
}

async function resetBuiltins() {
  resetting.value = true
  try {
    await store.resetDeliverableTemplates()
    message.success('内置模板已重置')
    const target = selected.value || templates.value[0]?.name
    if (target) await openTemplate(target)
  } catch (e) {
    message.error(e?.response?.data?.detail || '重置失败')
  } finally {
    resetting.value = false
  }
}

onUnmounted(() => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})

onMounted(async () => {
  await loadList()
  if (templates.value.length) openTemplate(templates.value[0].name)
})
</script>

<style scoped>
.deliverables-page { max-width: 1200px; }
.page-hint { display: block; margin-bottom: 16px; }
.layout { display: flex; gap: 16px; align-items: flex-start; }
.side { width: 240px; flex-shrink: 0; }
.editor { flex: 1; min-width: 0; }
.tpl-list { display: flex; flex-direction: column; gap: 4px; }
.tpl-item {
  padding: 8px 10px; border-radius: 8px; cursor: pointer;
  border: 1px solid transparent; transition: all 0.15s ease;
}
.tpl-item:hover { background: var(--color-neutral-wash-light); }
.tpl-item.active { border-color: var(--color-primary); background: var(--color-primary-bg); }
.tpl-label { font-size: 13px; font-weight: 600; color: var(--color-text-1); }
.tpl-name { font-size: 11px; color: var(--color-text-3); margin-top: 1px; }
.code-area :deep(textarea) { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; }
.preview-frame { width: 100%; height: 70vh; border: 0; }
</style>
