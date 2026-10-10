# AskFlow — 前端架构

```
frontend/
├── src/
│   ├── components/                         # 通用 UI 组件
│   │   ├── ChatHeader.vue                  # 聊天顶部栏：模型选择、风格切换
│   │   ├── ChatInput.vue                   # 聊天输入框：发送按钮、上传附件
│   │   ├── MessageList.vue                 # 消息列表渲染：Markdown/LaTeX/流式打字效果
│   │   ├── SessionSidebar.vue              # 会话侧边栏：会话列表、新建、删除
│   │   └── DocManagerModal.vue             # 文档管理弹窗：上传、删除、列表
│   │
│   ├── views/                              # 页面级组件
│   │   ├── Home.vue                        # 主聊天页：会话 + 消息列表 + 输入
│   │   ├── Login.vue                       # 登录页
│   │   └── Register.vue                    # 注册页
│   │   └── admin/                          # 管理后台
│   │       ├── AdminLayout.vue             #   后台布局：侧边导航 + 顶栏
│   │       ├── AdminDashboard.vue          #   仪表盘：用户数/文档数/日志量统计
│   │       ├── AdminSettings.vue           #   系统设置：LLM/检索/Agent/搜索/日志配置
│   │       ├── AdminUsers.vue              #   用户管理：创建/删除/改密码/权限
│   │
│   ├── stores/                             # Pinia 状态管理
│   │   ├── user.js                         # 用户认证状态：登录/注册/Token 管理
│   │   ├── admin.js                        # 管理后台 API 封装：配置/用户
│   │   └── theme.js                        # 主题切换：暗色/亮色模式
│   │
│   ├── router/                             # Vue Router 路由配置
│   │   └── index.js                        # 路由表：首页 → 登录 → 注册 → 管理后台
│   │
│   ├── http/                               # HTTP 请求层
│   │   └── interceptor.js                  # axios 封装：Token 注入、401 自动跳转登录
│   │
│   ├── config/                             # 前端运行时配置
│   │   └── app.js                          # API 地址等可配置项
│   │
│   ├── utils/                              # 工具函数
│   │   ├── markdown.js                     # Markdown/LaTeX 渲染配置（KaTeX）
│   │   └── uuid.js                         # UUID/Session ID 生成
│   │
│   ├── assets/                             # 静态资源
│   │   ├── base.css                        # CSS 基础变量
│   │   ├── main.css                        # 全局样式
│   │   └── logo.svg                        # 应用 Logo
│   │
│   ├── App.vue                             # Vue 根组件
│   └── main.js                             # 应用入口：Pinia + Router + Naive UI 加载
│
├── index.html                              # HTML 入口
├── package.json                            # 依赖与脚本
└── vite.config.js                          # Vite 构建配置（代理 /api → 后端）
```
