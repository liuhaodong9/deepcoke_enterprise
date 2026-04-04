<template>
    <el-container>
        <!--侧边栏-->
        <el-aside :style="{ width: isCollapese ? '0px' : '260px' }">
            <!-- 侧边栏完整内容 -->
            <div v-if="!isCollapese" class="sidebar-inner">
                <!-- 顶部：logo + 折叠 + 新对话 -->
                <div class="sidebar-top">
                    <div class="sidebar-header">
                        <div class="logo">
                            <span class="logo-mark"><img src="../assets/imgs/DeepCoke_logo.png" alt="DC" /></span>
                            DeepCoke
                        </div>
                        <button class="icon-btn" @click="toggleCollapse" title="收起侧边栏">
                            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="11 17 6 12 11 7"/>
                                <polyline points="18 17 13 12 18 7"/>
                            </svg>
                        </button>
                    </div>
                    <button class="new-chat-btn" @click="startNewChat">
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="12" y1="5" x2="12" y2="19"/>
                            <line x1="5" y1="12" x2="19" y2="12"/>
                        </svg>
                        <span>新对话</span>
                    </button>
                </div>

                <!-- 历史对话记录 -->
                <div class="chat-history">
                    <div class="history-label">历史对话</div>
                    <div
                      v-for="session in chatSessions"
                      :key="session.session_id"
                      class="chat-item"
                      :class="{ active: sessionId === session.session_id }"
                      @click="selectSession(session.session_id)"
                    >
                        <svg class="chat-item-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                        </svg>
                        <span class="chat-title">{{ session.title }}</span>
                        <el-dropdown trigger="click" @command="handleMenuCommand($event, session.session_id)">
                            <span class="chat-menu-btn" @click.stop>
                                <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                                    <circle cx="12" cy="5" r="1.5"/>
                                    <circle cx="12" cy="12" r="1.5"/>
                                    <circle cx="12" cy="19" r="1.5"/>
                                </svg>
                            </span>
                            <el-dropdown-menu slot="dropdown">
                                <el-dropdown-item command="rename">重命名</el-dropdown-item>
                                <el-dropdown-item command="delete">删除</el-dropdown-item>
                            </el-dropdown-menu>
                        </el-dropdown>
                    </div>
                </div>

                <!-- 侧边栏底部 -->
                <div class="sidebar-bottom">
                    <button class="sidebar-bottom-btn" @click="goLanding">
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                            <polyline points="9 22 9 12 15 12 15 22"/>
                        </svg>
                        <span>返回首页</span>
                    </button>
                </div>
            </div>
        </el-aside>

        <!--右侧内容主体区域-->
        <el-main>
            <!-- 顶栏 -->
            <div class="top-bar">
                <button v-if="isCollapese" class="icon-btn" @click="toggleCollapse" title="展开侧边栏">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="13 17 18 12 13 7"/>
                        <polyline points="6 17 11 12 6 7"/>
                    </svg>
                </button>
                <div class="top-bar-right">
                </div>
            </div>
            <router-view :sessionId="sessionId" :isCollapese="isCollapese" @update-sessions="fetchChatSessions"></router-view>
        </el-main>
    </el-container>
</template>

<script>

export default {
  data () {
    return {
      isCollapese: false,
      chatSessions: [],
      sessionId: '',
      userId: 'user123',
      apiBaseUrl: 'http://127.0.0.1:8000'
    }
  },
  methods: {
    toggleCollapse () {
      this.isCollapese = !this.isCollapese
    },
    goLanding () {
      this.$router.push('/landing')
    },
    async startNewChat () {
      try {
        const response = await fetch(`${this.apiBaseUrl}/new_session/?user_id=${this.userId}`, {
          method: 'POST'
        })
        const data = await response.json()
        this.sessionId = data.session_id

        this.chatSessions.unshift({
          session_id: this.sessionId,
          title: '新对话'
        })

        if (this.$route.path !== `/Home/MainDia/${this.sessionId}`) {
          setTimeout(() => {
            this.$router.push({ path: `/Home/MainDia/${this.sessionId}` })
          }, 100)
        }
      } catch (error) {
        console.error('创建会话失败:', error)
      }
    },
    goVoiceChat () {
      this.$router.push('/Home/VoiceAgent')
    },
    async selectSession (sessionId) {
      this.sessionId = sessionId
      if (this.$route.params.sessionId !== sessionId) {
        this.$router.push(`/Home/MainDia/${sessionId}`)
      }
    },
    async fetchChatSessions () {
      try {
        const response = await fetch(`${this.apiBaseUrl}/user_sessions/?user_id=${this.userId}`)
        const data = await response.json()
        if (!Array.isArray(data)) return

        this.chatSessions = data.map(session => ({
          session_id: session.session_id,
          title: session.title || `对话 ${session.session_id.slice(0, 6)}`
        }))
      } catch (error) {
        console.error('加载历史会话失败:', error)
      }
    },
    async handleMenuCommand (command, sessionId) {
      if (command === 'rename') {
        this.renameSession(sessionId)
      } else if (command === 'delete') {
        this.deleteSession(sessionId)
      }
    },
    async renameSession (sessionId) {
      const newTitle = prompt('请输入新的会话名称:')
      if (!newTitle) return

      try {
        const response = await fetch(`${this.apiBaseUrl}/rename_session/?session_id=${sessionId}&new_title=${encodeURIComponent(newTitle)}`, {
          method: 'PUT'
        })

        if (response.ok) {
          const session = this.chatSessions.find(s => s.session_id === sessionId)
          if (session) session.title = newTitle
        }
      } catch (error) {
        console.error('网络错误:', error)
      }
    },
    async deleteSession (sessionId) {
      if (!confirm('确定要删除这个会话吗？')) return

      try {
        const response = await fetch(`${this.apiBaseUrl}/delete_session/?session_id=${sessionId}`, {
          method: 'DELETE'
        })

        if (response.ok) {
          this.chatSessions = this.chatSessions.filter(s => s.session_id !== sessionId)

          if (this.sessionId === sessionId) {
            this.sessionId = this.chatSessions.length > 0 ? this.chatSessions[0].session_id : ''
          }
        }
      } catch (error) {
        console.error('网络错误:', error)
      }
    }
  },
  mounted () {
    this.fetchChatSessions()
  }
}
</script>

<style lang="less" scoped>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Noto+Sans+SC:wght@300;400;500;600;700&display=swap');

@dark: #0C0F14;
@dark-sidebar: #111318;
@dark-border: #1F2937;
@dark-hover: #1A1F28;
@accent: #E2E8F0;
@accent-dim: rgba(226, 232, 240, 0.06);
@text-bright: #F1F5F9;
@text-secondary: #94A3B8;
@text-muted: #64748B;

/* ===== 布局 ===== */
.el-container {
  display: flex;
  flex-direction: row;
  width: 100%;
  height: 100vh;
}

/* ===== 侧边栏 ===== */
.el-aside {
  background: @dark-sidebar;
  width: 260px;
  position: relative;
  height: 100vh;
  transition: width 0.2s ease;
  overflow: hidden;
  flex-shrink: 0;
  border-right: 1px solid @dark-border;
}

.sidebar-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 260px;
}

.sidebar-top {
  padding: 14px 12px;
  flex-shrink: 0;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  padding: 2px 0;
}

.logo {
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  font-weight: 700;
  color: @text-bright;
  display: flex;
  align-items: center;
  gap: 8px;
}

.logo-mark {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: @text-bright;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;

  img {
    width: 16px;
    height: 16px;
    object-fit: contain;
  }
}

/* ===== 通用图标按钮 ===== */
.icon-btn {
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: @text-muted;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.icon-btn:hover {
  background: @dark-hover;
  color: @text-secondary;
}

/* ===== 新对话按钮 ===== */
.new-chat-btn {
  width: 100%;
  height: 38px;
  border: 1px solid @dark-border;
  border-radius: 8px;
  background: transparent;
  color: @text-secondary;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 14px;
  cursor: pointer;
  transition: all 0.15s;
}

.new-chat-btn:hover {
  background: @dark-hover;
  border-color: #374151;
  color: @text-bright;
}

/* ===== 历史记录 ===== */
.chat-history {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px;
}

.history-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: @text-muted;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  padding: 8px 12px 6px;
}

.chat-history::-webkit-scrollbar {
  width: 4px;
}

.chat-history::-webkit-scrollbar-thumb {
  background: #374151;
  border-radius: 4px;
}

.chat-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  margin: 1px 0;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.12s;
  border: 1px solid transparent;
}

.chat-item:hover {
  background: @dark-hover;
}

.chat-item.active {
  background: @accent-dim;
  border-color: rgba(226, 232, 240, 0.2);
}

.chat-item-icon {
  color: @text-muted;
  flex-shrink: 0;
}

.chat-item.active .chat-item-icon {
  color: @accent;
}

.chat-title {
  flex: 1;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
  color: @text-secondary;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: left;
}

.chat-item.active .chat-title {
  color: @text-bright;
}

.chat-menu-btn {
  opacity: 0;
  color: @text-muted;
  padding: 2px 4px;
  border-radius: 4px;
  transition: all 0.12s;
  cursor: pointer;
  flex-shrink: 0;
}

.chat-item:hover .chat-menu-btn {
  opacity: 1;
}

.chat-menu-btn:hover {
  color: @text-secondary;
  background: rgba(255, 255, 255, 0.06);
}

/* ===== 侧边栏底部 ===== */
.sidebar-bottom {
  flex-shrink: 0;
  padding: 8px 12px 14px;
  border-top: 1px solid @dark-border;
}

.sidebar-bottom-btn {
  width: 100%;
  height: 36px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: @text-muted;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.sidebar-bottom-btn:hover {
  background: @dark-hover;
  color: @text-secondary;
}

/* ===== 右侧主体 ===== */
.el-main {
  background: @dark;
  width: 100%;
  height: 100vh;
  overflow: hidden;
  padding: 0;
  position: relative;
}

/* ===== 顶栏 ===== */
.top-bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  z-index: 100;
}

.top-bar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
</style>
