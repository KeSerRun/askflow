/** 共享表单验证规则 —— 与后端策略保持一致 */

export const usernameRules = [
  { required: true, message: '请输入用户名', trigger: 'blur' },
  { min: 6, message: '用户名长度至少为 6 位', trigger: 'blur' },
  {
    pattern: /^[a-zA-Z0-9]+$/,
    message: '用户名只能包含英文字母和数字',
    trigger: 'blur',
  },
]

export const passwordRules = [
  { required: true, message: '请输入密码', trigger: 'blur' },
  { min: 6, message: '密码长度至少为 6 位', trigger: 'blur' },
  {
    pattern: /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[a-zA-Z\d]{6,}$/,
    message: '密码必须同时包含大写、小写字母和数字',
    trigger: 'blur',
  },
]
