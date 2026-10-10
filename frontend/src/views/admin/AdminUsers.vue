<template>
  <div class="users-page">
    <n-h2>用户管理</n-h2>

    <!-- 操作栏 -->
    <n-space style="margin-bottom: 16px" justify="space-between" align="center">
      <n-button type="primary" @click="showAddModal = true">
        <template #icon>
          <n-icon :component="PersonAddOutline" />
        </template>
        新增用户
      </n-button>
      <n-text depth="3">共 {{ store.usersData?.total || 0 }} 个用户</n-text>
    </n-space>

    <n-data-table
      :columns="columns"
      :data="store.usersData?.items || []"
      :loading="store.loading"
      :bordered="true"
      :single-line="false"
      size="small"
      :pagination="pagination"
      @update:page="handlePageChange"
    />

    <!-- 新增用户对话框 -->
    <n-modal v-model:show="showAddModal" title="新增用户" preset="card" style="width: 420px">
      <n-form ref="addFormRef" :model="addForm" :rules="addRules" label-placement="top" size="medium">
        <n-form-item label="用户名" path="username">
          <n-input v-model:value="addForm.username" placeholder="6 位以上的英文字母或数字" />
        </n-form-item>
        <n-form-item label="密码" path="password">
          <n-input v-model:value="addForm.password" type="password" placeholder="至少 6 位,含大小写字母与数字" show-password-on="click" />
        </n-form-item>
        <n-form-item label="角色" path="role">
          <n-radio-group v-model:value="addForm.role">
            <n-radio value="user">普通用户</n-radio>
            <n-radio value="admin">管理员</n-radio>
          </n-radio-group>
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showAddModal = false">取消</n-button>
          <n-button type="primary" :loading="store.loading" @click="handleAddUser">确认创建</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 变更角色对话框 -->
    <n-modal v-model:show="showRoleModal" title="变更角色" preset="card" style="width: 380px">
      <n-space vertical>
        <n-text>用户：<strong>{{ roleTargetUser }}</strong></n-text>
        <n-radio-group v-model:value="roleTargetRole">
          <n-radio value="user">普通用户</n-radio>
          <n-radio value="admin">管理员</n-radio>
        </n-radio-group>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showRoleModal = false">取消</n-button>
          <n-button type="primary" :loading="store.loading" @click="handleChangeRole">确认</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 重置密码对话框 -->
    <n-modal v-model:show="showPwdModal" title="重置密码" preset="card" style="width: 400px">
      <n-space vertical>
        <n-text>用户：<strong>{{ pwdTargetUser }}</strong></n-text>
        <n-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-placement="top" size="medium">
          <n-form-item label="新密码" path="password">
            <n-input v-model:value="pwdForm.password" type="password" placeholder="至少 6 位" show-password-on="click" />
          </n-form-item>
          <n-form-item label="确认密码" path="confirm">
            <n-input v-model:value="pwdForm.confirm" type="password" placeholder="再次输入新密码" show-password-on="click" />
          </n-form-item>
        </n-form>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showPwdModal = false">取消</n-button>
          <n-button type="primary" :loading="store.loading" @click="handleResetPwd">确认重置</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { h, reactive, ref, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { useAdminStore } from '@/stores/admin'
import { useUserStore } from '@/stores/user'
import {
  NButton, NIcon, NSpace, NText, NDataTable,
  NModal, NForm, NFormItem, NInput,
  NRadio, NRadioGroup, NH2, NTag,
} from 'naive-ui'
import {
  PersonAddOutline, TrashOutline, ShieldCheckmarkOutline, KeyOutline,
} from '@vicons/ionicons5'
import { usernameRules, passwordRules } from '@/utils/validation'

const store = useAdminStore()
const userStore = useUserStore()
const message = useMessage()
const dialog = useDialog()

const showAddModal = ref(false)
const showRoleModal = ref(false)
const showPwdModal = ref(false)
const roleTargetUser = ref('')
const roleTargetRole = ref('user')
const pwdTargetUser = ref('')
const pwdFormRef = ref(null)
const pwdForm = reactive({ password: '', confirm: '' })
const pwdRules = {
  password: passwordRules,
  confirm: [
    { required: true, message: '请再次输入新密码' },
    {
      validator: (rule, value) => value === pwdForm.password || '两次密码输入不一致',
      trigger: 'blur',
    },
  ],
}

const addFormRef = ref(null)
const addForm = reactive({ username: '', password: '', role: 'user' })
const addRules = {
  username: usernameRules,
  password: passwordRules,
}

const pagination = reactive({
  page: 1,
  pageSize: 20,
  showSizePicker: false,
  pageCount: 1,
  prefix({ pageCount }) {
    return `共 ${store.usersData?.total || 0} 条`
  },
})

// 更新分页
function updatePagination() {
  pagination.pageCount = Math.ceil((store.usersData?.total || 0) / pagination.pageSize)
}

const columns = [
  { title: '用户名', key: 'username', width: 160 },
  {
    title: '角色',
    key: 'role',
    width: 100,
    render(row) {
      return h(NTag, {
        type: row.role === 'admin' ? 'warning' : 'default',
        size: 'small',
        bordered: false,
      }, { default: () => row.role === 'admin' ? '管理员' : '用户' })
    },
  },
  {
    title: '创建时间',
    key: 'created_at',
    render(row) {
      return row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '-'
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 180,
    render(row) {
      const isSelf = row.username === userStore.username
      return h(NSpace, { size: 4 }, {
        default: () => [
          h(NButton, {
            size: 'tiny',
            quaternary: true,
            type: 'primary',
            disabled: isSelf,
            onClick: () => openRoleModal(row.username, row.role),
          }, { default: () => '改角色', icon: () => h(NIcon, null, { default: () => h(ShieldCheckmarkOutline) }) }),
          h(NButton, {
            size: 'tiny',
            quaternary: true,
            type: 'warning',
            disabled: isSelf,
            onClick: () => openPwdModal(row.username),
          }, { default: () => '改密码', icon: () => h(NIcon, null, { default: () => h(KeyOutline) }) }),
          h(NButton, {
            size: 'tiny',
            quaternary: true,
            type: 'error',
            disabled: isSelf,
            onClick: () => confirmDelete(row.username),
          }, { default: () => '删除', icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) }),
        ],
      })
    },
  },
]

function handlePageChange(page) {
  pagination.page = page
  store.fetchUsers(page, pagination.pageSize)
}

function handleAddUser() {
  addFormRef.value?.validate((errors) => {
    if (errors) return
    store.createUser(addForm.username, addForm.password, addForm.role)
      .then(() => {
        message.success('用户创建成功')
        showAddModal.value = false
        addForm.username = ''
        addForm.password = ''
        addForm.role = 'user'
        updatePagination()
      })
      .catch(e => message.error(e.response?.data?.detail || '创建失败'))
  })
}

function openRoleModal(username, currentRole) {
  roleTargetUser.value = username
  roleTargetRole.value = currentRole
  showRoleModal.value = true
}

function handleChangeRole() {
  store.changeUserRole(roleTargetUser.value, roleTargetRole.value)
    .then(() => {
      message.success('角色已更新')
      showRoleModal.value = false
    })
    .catch(e => message.error(e.response?.data?.detail || '更新失败'))
}

function openPwdModal(username) {
  pwdTargetUser.value = username
  pwdForm.password = ''
  pwdForm.confirm = ''
  showPwdModal.value = true
}

function handleResetPwd() {
  pwdFormRef.value?.validate((errors) => {
    if (errors) return
    store.resetUserPassword(pwdTargetUser.value, pwdForm.password)
      .then(() => {
        message.success('密码已重置')
        showPwdModal.value = false
      })
      .catch(e => message.error(e.response?.data?.detail || '重置失败'))
  })
}

function confirmDelete(username) {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除用户 "${username}" 吗？此操作不可撤销。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: () => {
      store.deleteUser(username)
        .then(() => {
          message.success(`用户 ${username} 已删除`)
          updatePagination()
        })
        .catch(e => message.error(e.response?.data?.detail || '删除失败'))
    },
  })
}

onMounted(() => {
  store.fetchUsers().then(() => updatePagination())
})
</script>

<style scoped>
.users-page {
  width: 100%;
}
</style>
