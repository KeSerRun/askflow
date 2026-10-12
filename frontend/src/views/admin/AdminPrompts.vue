<template>
  <div class="prompts-page">
    <n-h2 style="margin-top: 0">Prompt 管理</n-h2>
    <n-text depth="3" style="font-size: 13px; display: block; margin-bottom: 12px">
      管理系统提示词（保存后立即热重载，作用于下一次对话）：<n-text code>identity</n-text>（系统身份，目录多预置，点「设为当前」切换）、
      <n-text code>workflow</n-text>（工作流）、<n-text code>style</n-text>（回答风格）。
      文件格式为 frontmatter + Markdown 正文，请保留开头的 <n-text code>---</n-text> 元信息。
    </n-text>

    <n-layout has-sider sider-placement="left" style="gap: 12px">
      <!-- 左侧：分类 + 列表 -->
      <n-layout-sider bordered width="260" :show-trigger="false" :native-scrollbar="true" style="height: 70vh">
        <div style="padding: 8px; display: flex; flex-direction: column; height: 100%;">
          <n-radio-group v-model:value="tab" size="small" style="margin-bottom: 10px">
            <n-radio-button value="identity">identity</n-radio-button>
            <n-radio-button value="workflow">workflow</n-radio-button>
            <n-radio-button value="style">style</n-radio-button>
          </n-radio-group>

          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px">
            <n-text depth="3" style="font-size: 12px">{{ tabLabel }}（{{ listItems.length }}）</n-text>
            <n-button size="tiny" type="primary" dashed @click="openCreate">新建</n-button>
          </div>

          <n-empty v-if="!listItems.length" description="暂无" size="small" style="padding: 12px 0" />
          <n-scrollbar v-else>
            <div
              v-for="item in listItems" :key="item.name"
              class="prompt-item" :class="{ active: current?.name === item.name }"
              @click="selectItem(item.name)"
            >
              <div class="prompt-item-head">
                <span class="prompt-item-name">{{ item.label || item.name }}</span>
                <n-tag v-if="tab === 'identity' && item.name === activeIdentity" size="tiny" type="success" :bordered="false">当前</n-tag>
                <n-button v-else-if="tab === 'identity'" size="tiny" quaternary type="primary" @click.stop="setActive(item.name)">设为当前</n-button>
              </div>
              <div class="prompt-item-desc">{{ item.description || item.name }}</div>
            </div>
          </n-scrollbar>
        </div>
      </n-layout-sider>

      <!-- 右侧：编辑器 -->
      <n-layout-content :native-scrollbar="true" style="height: 70vh">
        <div v-if="current" class="editor-wrap">
          <div class="editor-head">
            <n-text strong>{{ current.name }}</n-text>
            <n-text depth="3" style="font-size: 12px; margin-left: 8px">{{ current.path }}</n-text>
            <div style="flex: 1"></div>
            <n-button size="tiny" quaternary @click="refresh()">刷新</n-button>
          </div>
          <n-input
            v-model:value="current.content"
            type="textarea"
            :rows="20"
            placeholder="提示词内容…"
            class="editor-input"
            spellcheck="false"
          />
          <div class="editor-actions">
            <n-button type="primary" :loading="saving" @click="save">保存</n-button>
            <n-button v-if="tab === 'identity' && current?.name !== activeIdentity" type="primary" ghost :loading="saving" @click="setActive(current.name)">设为当前身份</n-button>
            <n-popconfirm @positive-click="remove" :disabled="!current">
              <template #trigger>
                <n-button type="error" quaternary :loading="deleting">删除</n-button>
              </template>
              确认删除「{{ current.name }}」？
            </n-popconfirm>
          </div>
        </div>

        <n-empty v-else description="从左侧选择要编辑的 Prompt，或在「identity / workflow / style」下新建" style="padding: 60px 0" />
      </n-layout-content>
    </n-layout>

    <!-- 新建名称弹窗 -->
    <n-modal v-model:show="createModal" preset="dialog" title="新建 Prompt" positive-text="下一步" negative-text="取消"
      @positive-click="confirmCreate" @negative-click="createModal = false">
      <n-input v-model:value="newName" placeholder="名称（字母/数字/._-，不含路径）" @keydown.enter="confirmCreate" />
    </n-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  NH2, NText, NLayout, NLayoutSider, NLayoutContent, NRadioGroup, NRadioButton,
  NButton, NInput, NPopconfirm, NEmpty, NScrollbar, NModal, NTag, useMessage,
} from 'naive-ui'
import { useAdminStore } from '@/stores/admin'

const store = useAdminStore()
const message = useMessage()

const tab = ref('identity')
const current = ref(null)
const saving = ref(false)
const deleting = ref(false)
const createModal = ref(false)
const newName = ref('')

const tabLabel = computed(() => (tab.value === 'identity' ? '身份' : tab.value === 'workflow' ? '工作流' : '回答风格'))
const activeIdentity = computed(() => store.promptsOverview?.identity_active || '')
const listItems = computed(() => {
  const o = store.promptsOverview
  if (!o) return []
  if (tab.value === 'workflow') return o.workflows || []
  if (tab.value === 'style') return o.styles || []
  return o.identities || []
})

async function refresh() {
  try {
    await store.fetchPrompts()
    const items = listItems.value
    if (!items.length) { current.value = null; return }
    const target = tab.value === 'identity'
      ? (activeIdentity.value || items[0].name)
      : (current.value?.name || items[0].name)
    if (items.some(i => i.name === target)) await selectItem(target)
    else await selectItem(items[0].name)
  } catch (e) { message.error(e.message) }
}

async function selectItem(name) {
  try {
    const data = await store.fetchPrompt(tab.value, name)
    current.value = { category: tab.value, name: data?.name || name, ...data }
  } catch (e) { message.error(e.message) }
}

async function setActive(name) {
  try {
    const res = await store.activateIdentity(name)
    message.success((res && res.message) || `已切换为「${name}」`)
    await refresh()
  } catch (e) { message.error(e.message) }
}

function openCreate() {
  newName.value = ''
  createModal.value = true
}

function confirmCreate() {
  const name = (newName.value || '').trim()
  if (!name) { message.warning('请输入名称'); return }
  const cname = name.charAt(0).toUpperCase() + name.slice(1)
  const tpl = tab.value === 'style'
    ? `---\nname: ${name}\ndescription: 一句话描述\n---\n\n风格指令正文…`
    : `---\nname: ${cname}\ndescription: 一句话描述\n---\n\n# ${cname}\n\n正文…`
  current.value = { category: tab.value, name: cname, path: '(新文件，保存后生成)', content: tpl }
  createModal.value = false
}

async function save() {
  if (!current.value || !(current.value.content || '').trim()) { message.warning('内容不能为空'); return }
  saving.value = true
  try {
    const res = await store.savePrompt(tab.value, current.value.name, current.value.content)
    message.success((res && res.message) || '已保存')
    await refresh()
  } catch (e) { message.error(e.message) }
  finally { saving.value = false }
}

async function remove() {
  if (!current.value) return
  deleting.value = true
  try {
    await store.deletePrompt(tab.value, current.value.name)
    message.success('已删除')
    current.value = null
    await refresh()
  } catch (e) { message.error(e.message) }
  finally { deleting.value = false }
}

// 切换分类时加载对应内容
watch(tab, () => { current.value = null; refresh() })

onMounted(() => { refresh() })
</script>

<style scoped>
.prompts-page { width: 100%; }
.prompt-item {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
  margin-bottom: 4px;
}
.prompt-item:hover { background: var(--color-hover); }
.prompt-item.active {
  background: rgba(24, 160, 88, 0.08);
  border-color: rgba(24, 160, 88, 0.4);
}
.prompt-item-name { font-size: 13px; font-weight: 600; }
.prompt-item-head { display: flex; align-items: center; gap: 6px; }
.prompt-item-desc {
  font-size: 12px;
  color: var(--color-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.editor-wrap { display: flex; flex-direction: column; height: 100%; padding: 4px; box-sizing: border-box; }
.editor-head { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; min-height: 28px; }
.editor-input { flex: 1; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; }
.editor-actions { display: flex; gap: 8px; margin-top: 8px; }
</style>