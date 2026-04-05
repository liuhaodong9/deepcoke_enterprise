<template>
  <div class="chat-outer" :class="{ 'pdf-open': pdfPanelVisible }">
  <div class="chat-wrapper">
    <!-- 聊天内容区域 -->
    <div class="chat-scroll" ref="chatScroll">
      <div class="chat-content">
        <!-- 欢迎区域（仅新会话且无消息时显示） -->
        <div v-if="messages.length <= 1 && sessionId === 'new'" class="welcome-area">
          <div class="welcome-logo">
            <img src="../assets/imgs/DeepCoke_logo.png" alt="DC" />
          </div>
          <h2 class="welcome-title">您好，欢迎使用 DeepCoke 焦化智能决策系统，请输入您的问题。</h2>
          <div class="quick-actions">
            <div class="quick-item" v-for="(q, i) in quickQuestions" :key="i" @click="sendQuickQuestion(q.text)">
              <span class="quick-icon">{{ q.icon }}</span>
              <div class="quick-text">
                <span class="quick-main">{{ q.main }}</span>
                <span class="quick-sub">{{ q.sub }}</span>
              </div>
            </div>
          </div>
        </div>

        <div
          v-for="(message, index) in messages"
          :key="index"
          class="message-row"
          :class="message.type"
          ref="lastMessage"
        >
          <!-- bot 头像 -->
          <div v-if="message.type === 'bot'" class="avatar bot-avatar">
            <img src="../assets/imgs/DeepCoke_logo.png" alt="DC" />
          </div>

          <div class="message-bubble" @click="onBubbleClick($event)">
            <!-- 深度思考指示器 -->
            <div v-if="message.thinking" class="thinking-indicator" @click="message.thinkExpanded = !message.thinkExpanded">
              <div class="thinking-header">
                <svg v-if="message.thinking === 'active'" class="thinking-spinner" viewBox="0 0 24 24" width="16" height="16">
                  <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" fill="none" stroke-dasharray="31.4 31.4" stroke-linecap="round"/>
                </svg>
                <svg v-else class="thinking-done-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
                <span class="thinking-label">
                  {{ message.thinking === 'active' ? '深度思考中…' : '已深度思考' }}
                </span>
                <span class="thinking-timer">{{ message.thinkSeconds }}s</span>
                <svg v-if="message.thinking === 'done'" class="thinking-chevron" :class="{ expanded: message.thinkExpanded }" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
              </div>
              <div v-if="message.thinkExpanded && message.thinkContent" class="thinking-content" v-html="message.thinkContent"></div>
            </div>
            <div v-if="message.text" class="md-content" v-html="renderMarkdown(message.text)"></div>
            <div v-else-if="message.type === 'bot' && !message.thinking" class="loading-hint">
              <div class="loading-dots"><span></span><span></span><span></span></div>
              <div class="loading-text">DeepCoke 正在分析您的问题…</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="input-area">
      <div class="input-wrapper">
        <!-- 隐藏文件选择器 -->
        <input
          ref="filePicker"
          type="file"
          multiple
          style="display:none"
          @change="onFilesSelected"
        />

        <!-- 附件按钮 -->
        <button class="input-icon-btn" @click="openFilePicker" title="添加文件">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
          </svg>
        </button>

        <el-input
          ref="inputBox"
          v-model="newMessage"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 6 }"
          placeholder="给 DeepCoke 发送消息..."
          @keydown.enter.native.prevent="sendMessage"
          class="input-box"
        ></el-input>

        <!-- 发送按钮 -->
        <button class="send-btn" :class="{ 'has-text': newMessage.trim() }" @click="sendMessage">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="22" y1="2" x2="11" y2="13"/>
            <polygon points="22 2 15 22 11 13 2 9 22 2"/>
          </svg>
        </button>
      </div>
      <div class="input-footer">内容由 AI 生成，请仔细甄别</div>
    </div>
    <chart-dialog ref="chartDialog" />
  </div>

  <!-- 右侧 PDF 全文面板 -->
  <div v-if="pdfPanelVisible" class="pdf-panel">
    <div class="pdf-panel-header">
      <span class="pdf-panel-title">📄 文献原文</span>
      <button class="pdf-panel-close" @click="closePdfPanel">✕</button>
    </div>
    <iframe :src="pdfPanelUrl" class="pdf-panel-iframe"></iframe>
  </div>
  </div>
</template>

<script>
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import ChartDialog from './ChartDialog.vue'

// 初始化 markdown-it（比 marked 更可靠地处理流式标题/列表）
const md = new MarkdownIt({
  html: true,
  breaks: true,
  linkify: true,
  highlight: function (code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang }).value
    }
    return hljs.highlightAuto(code).value
  }
})

export default {
  components: { ChartDialog },
  props: ['sessionId', 'isCollapese'],
  data () {
    return {
      messages: [],
      newMessage: '',
      apiBaseUrl: 'http://127.0.0.1:8000',
      isUserScrolling: false,
      localSessionId: '',
      attachments: [],
      isDictating: false,
      voiceMode: false,
      chartDataStore: [],
      recognition: null,
      pdfPanelVisible: false,
      pdfPanelUrl: '',
      quickQuestions: [
        { icon: '⚗', main: '优化配煤方案', sub: '基于煤质指标自动推算', text: '帮我优化一个配煤方案' },
        { icon: '📊', main: '预测焦炭质量', sub: '灰分、硫分、强度预测', text: '预测这批煤的焦炭质量' },
        { icon: '📚', main: '查阅焦化文献', sub: '6000+ 篇专业知识库', text: '关于捣固焦工艺的文献有哪些？' },
        { icon: '🔧', main: '工艺问题诊断', sub: '温度场异常分析', text: '焦炉温度场异常，可能的原因有哪些？' }
      ]
    }
  },
  methods: {
    renderMarkdown (text) {
      // 保护进度条 HTML 和 details 标签不被转义
      const htmlPlaceholders = []
      let preprocessed = text

      // 拦截 ECharts 图表标记，替换为按钮
      preprocessed = preprocessed.replace(/<!--ECHART:([\s\S]*?)-->/g, (match, jsonStr) => {
        try {
          const desc = JSON.parse(jsonStr)
          // 用 title + chartType 做 key 去重（避免 renderMarkdown 多次调用重复 push）
          const key = `${desc.chartType}__${desc.title}`
          let chartId = this.chartDataStore.findIndex(d => `${d.chartType}__${d.title}` === key)
          if (chartId === -1) {
            chartId = this.chartDataStore.length
            this.chartDataStore.push(desc)
          }
          const idx = htmlPlaceholders.length
          htmlPlaceholders.push(
            `<button class="echart-btn" data-chart-id="${chartId}">📊 ${desc.title || '查看图表'}</button>`
          )
          return `<!--PH${idx}-->`
        } catch (e) { return '' }
      })

      preprocessed = preprocessed.replace(/<div class="pipeline-progress">[\s\S]*?progress-pct[^>]*>[\s\S]*?<\/div>\s*<\/div>/gi, (match) => {
        const idx = htmlPlaceholders.length
        htmlPlaceholders.push(match)
        return `<!--PH${idx}-->`
      })
      preprocessed = preprocessed.replace(/<\/?(?:details|summary)[^>]*>/gi, (match) => {
        const idx = htmlPlaceholders.length
        htmlPlaceholders.push(match)
        return `<!--PH${idx}-->`
      })
      // 保护 Agent 交互按钮
      preprocessed = preprocessed.replace(/<div class="agent-actions">[\s\S]*?<\/div>/gi, (match) => {
        const idx = htmlPlaceholders.length
        htmlPlaceholders.push(match)
        return `<!--PH${idx}-->`
      })
      // 保护文献图表卡片（<div> 包裹的图片+标题），补全相对路径
      preprocessed = preprocessed.replace(/<div\s+style="margin:12px[^"]*">[\s\S]*?<\/div>/gi, (match) => {
        const fixed = match.replace(/src="\/static\//g, `src="${this.apiBaseUrl}/static/`)
        const idx = htmlPlaceholders.length
        htmlPlaceholders.push(fixed)
        return `\n<!--PH${idx}-->\n`
      })
      // 保护内嵌图片（如有），补全相对路径为完整 API URL
      preprocessed = preprocessed.replace(/<img\s+[^>]+>/gi, (match) => {
        const fixed = match.replace(/src="\/static\//g, `src="${this.apiBaseUrl}/static/`)
        const idx = htmlPlaceholders.length
        htmlPlaceholders.push(fixed)
        return `\n<!--PH${idx}-->\n`
      })
      // 保护链接（含参考文献的 ref-link 和下载链接），连带后面的 <br> 一起保护
      preprocessed = preprocessed.replace(/<a\s[^>]*>[\s\S]*?<\/a>(?:\s*<br\s*\/?>)?/gi, (match) => {
        const idx = htmlPlaceholders.length
        htmlPlaceholders.push(match)
        return `\n<!--PH${idx}-->\n`
      })

      // 将 <br> 转为换行
      preprocessed = preprocessed.replace(/\s*<br\s*\/?>\s*/gi, '\n')

      // 修正 Markdown 格式：LLM 流式输出常见问题
      // 1. 标题前必须有空行（行内 #### 无法识别）
      preprocessed = preprocessed.replace(/([^\n])(#{1,6}\s)/g, '$1\n\n$2')
      // 2. ###\n标题 → ### 标题（标题文字和 # 必须同一行）
      preprocessed = preprocessed.replace(/^(#{1,6})\s*\n+\s*(\S)/gm, '$1 $2')
      // 3. ####标题 → #### 标题（# 后必须有空格）
      preprocessed = preprocessed.replace(/^(#{1,6})([^\s#])/gm, '$1 $2')
      // 4. 中文序号前换行
      preprocessed = preprocessed.replace(/([^\n])([一二三四五六七八九十]+、)/g, '$1\n\n$2')
      // 5. 数字列表前换行
      preprocessed = preprocessed.replace(/([^\n])(\d+\.\s)/g, '$1\n\n$2')

      // KaTeX 公式渲染
      preprocessed = preprocessed
        .replace(/\$\$(.*?)\$\$/gs, (_, equation) => {
          return katex.renderToString(equation.trim(), {
            throwOnError: false,
            displayMode: true
          })
        })
        .replace(/(^|[^$\\])\$([^$\n]+?)\$(?![0-9$])/g, (_, before, equation) => {
          return before + katex.renderToString(equation.trim(), {
            throwOnError: false,
            displayMode: false
          })
        })

      // 使用 markdown-it 渲染（比 marked 更可靠地处理标题和列表）
      let html = md.render(preprocessed)

      // 在 marked 处理之后再还原受保护的 HTML 片段（避免 marked 破坏原始 HTML）
      html = html.replace(/<!--PH(\d+)-->/g, (_, idx) => {
        return htmlPlaceholders[parseInt(idx)]
      })

      // 从参考文献区的 ref-link 中提取 refNum → {href, excerpt}
      const refMap = {}
      const excerptRegex = /<a[^>]*data-ref="(\d+)"[^>]*href="([^"]*)"[^>]*data-excerpt="([^"]*)"[^>]*/g
      let refMatch
      while ((refMatch = excerptRegex.exec(html)) !== null) {
        refMap[refMatch[1]] = { href: refMatch[2], excerpt: refMatch[3] }
      }
      // 也匹配属性顺序不同的情况
      const excerptRegex2 = /<a[^>]*href="([^"]*)"[^>]*data-ref="(\d+)"[^>]*data-excerpt="([^"]*)"[^>]*/g
      while ((refMatch = excerptRegex2.exec(html)) !== null) {
        if (!refMap[refMatch[2]]) {
          refMap[refMatch[2]] = { href: refMatch[1], excerpt: refMatch[3] }
        }
      }

      // 将正文中的 [N] 引用标注转为可点击链接（排除已在 <a> 标签内的）
      html = html.replace(/(?:<a[^>]*>[\s\S]*?<\/a>)|(\[(\d{1,2})\])/g, (match, cite, num) => {
        if (!cite) return match
        const ref = refMap[num]
        if (ref) {
          return `<a class="inline-cite" href="${ref.href}" data-ref="${num}" data-excerpt="${ref.excerpt}">[${num}]</a>`
        }
        return match
      })

      return html
    },
    scrollToBottom () {
      this.$nextTick(() => {
        const el = this.$refs.chatScroll
        if (el) el.scrollTop = el.scrollHeight
      })
    },
    openFilePicker () {
      if (this.$refs.filePicker) this.$refs.filePicker.click()
    },
    onFilesSelected (e) {
      const files = Array.from(e.target.files || [])
      if (!files.length) return
      this.attachments.push(...files)
      const names = files.map(f => f.name).join('、')
      this.$message && this.$message.success(`已选择 ${files.length} 个文件：${names}`)
      e.target.value = ''
    },
    toggleDictation () {
      if (this.isDictating) {
        if (this.recognition) this.recognition.stop()
        this.isDictating = false
        return
      }
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition
      if (!SR) {
        this.$message && this.$message.warning('当前浏览器不支持语音输入')
        return
      }
      this.recognition = new SR()
      this.recognition.lang = 'zh-CN'
      this.recognition.continuous = true
      this.recognition.interimResults = true

      this.recognition.onstart = () => { this.isDictating = true }
      this.recognition.onresult = (event) => {
        let txt = ''
        for (let i = event.resultIndex; i < event.results.length; i++) {
          txt += event.results[i][0].transcript
        }
        if (txt) this.newMessage = (this.newMessage + ' ' + txt).trim()
      }
      this.recognition.onerror = () => { this.isDictating = false }
      this.recognition.onend = () => { this.isDictating = false }
      this.recognition.start()
    },
    toggleVoiceMode () {
      this.voiceMode = !this.voiceMode
      if (!this.voiceMode) window.speechSynthesis.cancel()
    },
    speak (text) {
      if (!this.voiceMode || !window.speechSynthesis) return
      const u = new SpeechSynthesisUtterance(text)
      u.lang = 'zh-CN'
      window.speechSynthesis.cancel()
      window.speechSynthesis.speak(u)
    },
    onBubbleClick (e) {
      // 参考文献 PDF 链接 或 正文内联引用：打开 PDF 查看器
      const pdfLink = e.target.closest('.ref-link') || e.target.closest('.inline-cite')
      if (pdfLink) {
        e.preventDefault()
        let href = pdfLink.getAttribute('href')
        if (href) {
          // 将 /pdf/N?... 转为 /pdf_viewer/N?... 以使用带高亮的查看器
          href = href.replace(/^\/pdf\//, '/pdf_viewer/')
          this.pdfPanelUrl = `${this.apiBaseUrl}${href}`
          this.pdfPanelVisible = true
        }
        return
      }
      // ECharts 图表按钮
      const chartBtn = e.target.closest('.echart-btn')
      if (chartBtn) {
        e.preventDefault()
        const chartId = parseInt(chartBtn.dataset.chartId)
        const desc = this.chartDataStore[chartId]
        if (desc) this.$refs.chartDialog.open(desc)
        return
      }
      // Agent 指令按钮
      const btn = e.target.closest('[data-agent-action]')
      if (!btn) return
      e.preventDefault()
      const action = btn.getAttribute('data-agent-action')
      if (action) {
        // 禁用所有按钮（防止重复点击）
        const container = btn.closest('.agent-actions')
        if (container) {
          container.querySelectorAll('.agent-btn').forEach(b => {
            b.disabled = true
            b.style.opacity = '0.5'
            b.style.pointerEvents = 'none'
          })
        }
        // 发送 Agent 指令
        this.newMessage = action
        this.sendMessage()
      }
    },
    closePdfPanel () {
      this.pdfPanelVisible = false
      this.pdfPanelUrl = ''
    },
    sendQuickQuestion (text) {
      this.newMessage = text
      this.sendMessage()
    },
    async sendMessage () {
      if (!this.newMessage.trim()) return
      const userText = this.newMessage
      this.newMessage = ''

      // Agent 指令：显示友好文本而非原始指令
      const agentLabels = {
        '__AGENT:confirm_blend__': '确认，开始优化',
        '__AGENT:add_constraints__': '我要调整条件',
        '__AGENT:auto_retry__': '让质量分析师自动调整再试',
        '__AGENT:free_input__': '我自己输入条件',
        '__AGENT:confirm_add_coal__': '确认录入',
        '__AGENT:confirm_delete_coal__': '确认删除',
        '__AGENT:confirm_update_coal__': '确认更新',
        '__AGENT:cancel_data__': '取消操作',
        '__AGENT:use_all_coals__': '用全部煤种优化'
      }
      let displayText = userText
      if (userText.startsWith('__AGENT:')) {
        displayText = agentLabels[userText] || userText.replace(/__AGENT:|__/g, '').replace(/_/g, ' ')
        // pick_plan:X → 选择方案 X
        if (userText.includes('pick_plan:')) {
          const strategy = userText.match(/pick_plan:(\w+)/)?.[1] || '?'
          displayText = `选择方案 ${strategy}`
        }
        // adjust:xxx → 显示"调整约束条件"
        if (userText.includes(':adjust:')) {
          displayText = '调整约束条件'
        }
      }
      this.messages.push({ text: displayText, type: 'user' })

      const botMessage = { text: '', type: 'bot', thinking: null, thinkSeconds: 0, thinkContent: '', thinkExpanded: false }
      this.messages.push(botMessage)
      this.scrollToBottom()

      let sessionToUse = this.sessionId
      if (this.sessionId === 'new') {
        try {
          const response = await fetch(`${this.apiBaseUrl}/new_session/?user_id=user123`, { method: 'POST' })
          const data = await response.json()
          this.localSessionId = data.session_id
          this.$emit('update-sessions')
          sessionToUse = this.localSessionId
        } catch (error) {
          console.error('创建新会话失败:', error)
          return
        }
      }

      try {
        const response = await fetch(
          `${this.apiBaseUrl}/chat/?session_id=${sessionToUse}&user_message=${encodeURIComponent(userText)}`,
          { method: 'POST' }
        )
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let botReply = ''
        let buffer = '' // 缓冲区，按 __PG__ / __/PG__ 标记分割进度块
        const thinkStart = Date.now()
        let thinkTimer = null
        let isThinking = false

        // 启动思考计时器
        const startThinking = () => {
          if (isThinking) return
          isThinking = true
          this.$set(botMessage, 'thinking', 'active')
          if (!thinkTimer) {
            thinkTimer = setInterval(() => {
              this.$set(botMessage, 'thinkSeconds', Math.round((Date.now() - thinkStart) / 1000))
            }, 100)
          }
        }

        // 结束思考
        const stopThinking = () => {
          if (!isThinking) return
          isThinking = false
          this.$set(botMessage, 'thinkSeconds', Math.round((Date.now() - thinkStart) / 1000))
          this.$set(botMessage, 'thinking', 'done')
        }

        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          // 按 __PG__ / __/PG__ 标记分割进度块和正文
          while (true) {
            const pgStart = buffer.indexOf('__PG__')
            const pgEnd = buffer.indexOf('__/PG__')

            if (pgStart !== -1 && pgEnd !== -1 && pgEnd > pgStart) {
              // 完整的进度块：__PG__...content...__/PG__
              // pgStart 之前的是正文
              const textBefore = buffer.substring(0, pgStart)
              if (textBefore.trim()) {
                if (isThinking) stopThinking()
                botReply += textBefore
                botMessage.text = botReply
              }
              // 提取进度 HTML（去掉标记）
              const progressHtml = buffer.substring(pgStart + 6, pgEnd)
              startThinking()
              this.$set(botMessage, 'thinkContent', progressHtml)
              // 移除已处理的部分
              buffer = buffer.substring(pgEnd + 7)
            } else if (pgStart !== -1 && pgEnd === -1) {
              // 有开始标记但没结束标记 → 等更多数据
              // 先把开始标记之前的正文输出
              const textBefore = buffer.substring(0, pgStart)
              if (textBefore.trim()) {
                if (isThinking) stopThinking()
                botReply += textBefore
                botMessage.text = botReply
              }
              buffer = buffer.substring(pgStart)
              break
            } else {
              // 没有进度标记 → 全部是正文
              if (buffer.trim()) {
                if (isThinking) stopThinking()
                botReply += buffer
                botMessage.text = botReply
              }
              buffer = ''
              break
            }
          }

          this.$nextTick(() => this.scrollToBottom())
        }

        // 处理缓冲区残留
        if (buffer.trim()) {
          botReply += buffer
          botMessage.text = botReply
        }

        // 流结束，确保思考状态正确
        if (isThinking) stopThinking()
        if (thinkTimer) { clearInterval(thinkTimer); thinkTimer = null }

        if (this.voiceMode && botReply.trim()) this.speak(botReply)
      } catch (error) {
        console.error('发送消息失败:', error)
        this.streamReply(botMessage, '对不起，网络异常，请稍后再试。')
      }

      this.attachments = []
      this.scrollToBottom()
    },
    async loadChatHistory () {
      if (!this.sessionId) return
      try {
        const response = await fetch(`${this.apiBaseUrl}/messages/?session_id=${this.sessionId}`)
        const data = await response.json()
        this.messages = data
          .filter(msg => msg.type !== 'user' || msg.text.trim() !== '')
          .map(msg => ({
            text: msg.type === 'bot'
              ? msg.text.replace(/__PG__[\s\S]*?__\/PG__/g, '').replace(/<div class="pipeline-progress">[\s\S]*?<\/div>\s*<\/div>/gi, '')
              : msg.text,
            type: msg.type
          }))
        if (this.sessionId === 'new') {
          this.streamWelcomeMessage()
        }
        this.scrollToBottom()
      } catch (error) {
        console.error('加载聊天记录失败:', error)
      }
    },
    streamReply (botMessage, fullText) {
      let i = 0
      const interval = setInterval(() => {
        if (i < fullText.length) {
          botMessage.text += fullText[i]
          i++
        } else {
          clearInterval(interval)
        }
      }, 50)
    },
    streamWelcomeMessage () {
      const botMessage = { text: '', type: 'bot' }
      this.messages.push(botMessage)
      this.streamReply(botMessage, '您好，欢迎使用 DeepCoke 焦化智能决策系统，请输入您的问题。')
    }
  },
  watch: {
    sessionId () {
      this.loadChatHistory()
    },
    messages () {
      this.scrollToBottom()
    }
  },
  mounted () {
    if (this.sessionId === 'new') {
      const botMessage = { text: '', type: 'bot' }
      this.messages.push(botMessage)
      this.streamReply(botMessage, '您好，欢迎使用 DeepCoke 焦化智能决策系统，请输入您的问题。')
    } else {
      this.loadChatHistory()
    }

    // 引用悬浮气泡：事件委托
    let tooltip = null
    this.$el.addEventListener('mouseover', (e) => {
      const cite = e.target.closest('.inline-cite, .ref-link')
      if (!cite) return
      const excerpt = cite.dataset.excerpt
      if (!excerpt) return
      // 创建气泡
      if (tooltip) tooltip.remove()
      tooltip = document.createElement('div')
      tooltip.className = 'cite-tooltip'
      tooltip.innerHTML = `<div class="cite-tooltip-title">📄 原文摘录</div><div class="cite-tooltip-text">${excerpt}</div>`
      document.body.appendChild(tooltip)
      // 定位到元素上方
      const rect = cite.getBoundingClientRect()
      tooltip.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - 380)) + 'px'
      tooltip.style.top = (rect.top + window.scrollY - tooltip.offsetHeight - 8) + 'px'
      // 如果上方放不下，放到下方
      if (rect.top - tooltip.offsetHeight - 8 < 0) {
        tooltip.style.top = (rect.bottom + window.scrollY + 8) + 'px'
      }
    })
    this.$el.addEventListener('mouseout', (e) => {
      const cite = e.target.closest('.inline-cite, .ref-link')
      if (cite && tooltip) {
        tooltip.remove()
        tooltip = null
      }
    })
  }
}
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Noto+Sans+SC:wght@300;400;500;600;700&display=swap');

/* ===== 整体布局 ===== */
.chat-outer {
  display: flex;
  height: 100vh;
  width: 100%;
  overflow: hidden;
}
.chat-wrapper {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #0C0F14;
  flex: 1;
  min-width: 0;
  transition: flex 0.3s ease;
}
.chat-outer.pdf-open .chat-wrapper {
  flex: 0 0 50%;
}

/* ===== 右侧 PDF 面板 ===== */
.pdf-panel {
  flex: 0 0 50%;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #111827;
  border-left: 2px solid #1e293b;
}
.pdf-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: #1f2937;
  border-bottom: 1px solid #374151;
  flex-shrink: 0;
}
.pdf-panel-title {
  color: #93c5fd;
  font-size: 14px;
  font-weight: 600;
}
.pdf-panel-close {
  background: #374151;
  border: 1px solid #4b5563;
  color: #e5e7eb;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.pdf-panel-close:hover {
  background: #ef4444;
  border-color: #ef4444;
}
.pdf-panel-iframe {
  flex: 1;
  border: none;
  width: 100%;
}

/* ===== 消息滚动区 ===== */
.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding-top: 56px;
}

.chat-scroll::-webkit-scrollbar {
  width: 6px;
}

.chat-scroll::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.06);
  border-radius: 3px;
}

.chat-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.12);
}

.chat-content {
  max-width: 740px;
  margin: 0 auto;
  padding: 16px 24px 24px;
}

/* ===== 欢迎区域 ===== */
.welcome-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 0 40px;
}

.welcome-logo {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  background: #F1F5F9;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
  box-shadow: 0 8px 24px rgba(255, 255, 255, 0.06);
}

.welcome-logo img {
  width: 36px;
  height: 36px;
  object-fit: contain;
}

.welcome-title {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 17px;
  color: #94A3B8;
  font-weight: 400;
  margin: 0 0 28px;
  text-align: center;
}

.quick-actions {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  width: 100%;
  max-width: 520px;
}

.quick-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  background: #161A22;
  border: 1px solid #1F2937;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.quick-item:hover {
  background: #1A1F28;
  border-color: #374151;
}

.quick-icon {
  font-size: 18px;
  flex-shrink: 0;
  margin-top: 1px;
}

.quick-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.quick-main {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
  color: #F1F5F9;
  font-weight: 500;
}

.quick-sub {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 12px;
  color: #64748B;
}

/* ===== 消息行 ===== */
.message-row {
  display: flex;
  gap: 14px;
  margin: 20px 0;
  align-items: flex-start;
}

.message-row.user {
  flex-direction: row-reverse;
}

/* ===== 头像 ===== */
.avatar {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  overflow: hidden;
  flex-shrink: 0;
}

.bot-avatar {
  background: #F1F5F9;
  display: flex;
  align-items: center;
  justify-content: center;
}

.bot-avatar img {
  width: 20px;
  height: 20px;
  object-fit: contain;
}

/* ===== 消息气泡 ===== */
.message-bubble {
  max-width: 85%;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 15px;
  line-height: 1.7;
  word-wrap: break-word;
  text-align: left;
}

.message-row.bot .message-bubble {
  color: #E2E8F0;
  padding: 14px 18px;
  background: #161A22;
  border: 1px solid #1F2937;
  border-radius: 4px 18px 18px 18px;
}

.message-row.user .message-bubble {
  background: rgba(255, 255, 255, 0.06);
  color: #F1F5F9;
  padding: 12px 18px;
  border-radius: 18px 18px 4px 18px;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

/* ===== Markdown 内容样式（ChatGPT 风格） ===== */
.message-bubble .md-content { word-break: break-word; }

/* 标题层级 */
::v-deep .message-bubble h1 {
  font-size: 20px;
  font-weight: 700;
  color: #F1F5F9;
  margin: 24px 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #1F2937;
}
::v-deep .message-bubble h2 {
  font-size: 17px;
  font-weight: 600;
  color: #F1F5F9;
  margin: 20px 0 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
::v-deep .message-bubble h3 {
  font-size: 15px;
  font-weight: 600;
  color: #E2E8F0;
  margin: 16px 0 8px;
}
::v-deep .message-bubble h1:first-child,
::v-deep .message-bubble h2:first-child,
::v-deep .message-bubble h3:first-child { margin-top: 0; }

/* 段落 */
::v-deep .message-bubble p { margin: 8px 0; line-height: 1.75; }

/* 列表 */
::v-deep .message-bubble ul,
::v-deep .message-bubble ol {
  padding-left: 24px;
  margin: 10px 0;
}
::v-deep .message-bubble li {
  margin: 4px 0;
  line-height: 1.7;
}
::v-deep .message-bubble li::marker {
  color: #64748B;
}
::v-deep .message-bubble ul li { list-style-type: disc; }
::v-deep .message-bubble ul li ul li { list-style-type: circle; }

/* 粗体 / 强调 */
::v-deep .message-bubble strong {
  color: #F8FAFC;
  font-weight: 600;
}
::v-deep .message-bubble em {
  color: #CBD5E1;
  font-style: italic;
}

/* 行内代码 */
::v-deep .message-bubble code {
  background: rgba(56, 189, 248, 0.08);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
  font-family: 'JetBrains Mono', monospace;
  color: #38BDF8;
  border: 1px solid rgba(56, 189, 248, 0.12);
}

/* 代码块 */
::v-deep .message-bubble pre {
  background: #0D1117;
  border: 1px solid #1F2937;
  border-radius: 10px;
  padding: 16px;
  margin: 12px 0;
  overflow-x: auto;
}
::v-deep .message-bubble pre code {
  background: transparent;
  padding: 0;
  color: #CBD5E1;
  border: none;
  font-size: 13px;
  line-height: 1.6;
}

/* 链接 */
::v-deep .message-bubble a {
  color: #38BDF8;
  text-decoration: none;
  border-bottom: 1px solid rgba(56, 189, 248, 0.3);
  transition: border-color 0.2s;
}
::v-deep .message-bubble a:hover {
  border-bottom-color: #38BDF8;
}

/* 表格 */
::v-deep .message-bubble table {
  border-collapse: separate;
  border-spacing: 0;
  margin: 12px 0;
  width: 100%;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #1F2937;
  font-size: 14px;
}
::v-deep .message-bubble th {
  background: rgba(56, 189, 248, 0.06);
  color: #E2E8F0;
  font-weight: 600;
  padding: 10px 14px;
  text-align: left;
  border-bottom: 1px solid #1F2937;
  font-size: 13px;
  text-transform: none;
  letter-spacing: 0.02em;
}
::v-deep .message-bubble td {
  padding: 9px 14px;
  text-align: left;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  color: #CBD5E1;
}
::v-deep .message-bubble tr:last-child td {
  border-bottom: none;
}
::v-deep .message-bubble tbody tr:hover {
  background: rgba(255, 255, 255, 0.02);
}

/* 引用块 */
::v-deep .message-bubble blockquote {
  margin: 12px 0;
  padding: 10px 16px;
  border-left: 3px solid #38BDF8;
  background: rgba(56, 189, 248, 0.04);
  border-radius: 0 8px 8px 0;
  color: #94A3B8;
  font-size: 14px;
}
::v-deep .message-bubble blockquote p {
  margin: 4px 0;
}

/* 分隔线 */
::v-deep .message-bubble hr {
  border: none;
  height: 1px;
  background: linear-gradient(90deg, transparent, #334155, transparent);
  margin: 20px 0;
}

/* 图片 */
::v-deep .message-bubble img {
  max-width: 100%;
  border-radius: 8px;
  margin: 8px 0;
}

/* ===== 推理过程折叠块 ===== */
::v-deep .message-bubble details {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid #1F2937;
  border-radius: 8px;
  padding: 10px 14px;
  margin: 8px 0 12px;
}
::v-deep .message-bubble details summary {
  cursor: pointer;
  color: #94A3B8;
  font-size: 14px;
  user-select: none;
}
::v-deep .message-bubble details summary:hover {
  color: #F1F5F9;
}
::v-deep .message-bubble details[open] summary {
  margin-bottom: 8px;
  border-bottom: 1px solid #1F2937;
  padding-bottom: 6px;
}
::v-deep .message-bubble details p,
::v-deep .message-bubble details li {
  font-size: 13px;
  color: #94A3B8;
}

/* ===== 加载动画 ===== */
.loading-hint {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  padding: 4px 0;
}

.loading-text {
  font-size: 13px;
  color: #94A3B8;
  animation: pulse-text 2s infinite ease-in-out;
}

@keyframes pulse-text {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

.loading-dots {
  display: flex;
  gap: 5px;
  padding: 8px 0;
}

.loading-dots span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #94A3B8;
  animation: dots 1.4s infinite ease-in-out;
}

.loading-dots span:nth-child(1) { animation-delay: 0s; }
.loading-dots span:nth-child(2) { animation-delay: 0.2s; }
.loading-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dots {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

/* ===== 深度思考指示器 ===== */
.thinking-indicator {
  cursor: pointer;
  user-select: none;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.thinking-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: #94A3B8;
  transition: color 0.2s;
}

.thinking-header:hover {
  color: #CBD5E1;
}

.thinking-spinner {
  animation: think-spin 1s linear infinite;
  color: #38BDF8;
  flex-shrink: 0;
}

@keyframes think-spin {
  to { transform: rotate(360deg); }
}

.thinking-done-icon {
  color: #38BDF8;
  flex-shrink: 0;
}

.thinking-label {
  font-family: 'Noto Sans SC', sans-serif;
  font-weight: 500;
}

.thinking-timer {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  color: #64748B;
  min-width: 28px;
}

.thinking-chevron {
  margin-left: auto;
  transition: transform 0.2s;
  color: #64748B;
}

.thinking-chevron.expanded {
  transform: rotate(180deg);
}

.thinking-content {
  margin-top: 10px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid #1F2937;
  border-radius: 8px;
  font-size: 13px;
  color: #94A3B8;
  max-height: 300px;
  overflow-y: auto;
}

.thinking-content::-webkit-scrollbar {
  width: 4px;
}

.thinking-content::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.08);
  border-radius: 2px;
}

/* ===== 输入区域 ===== */
.input-area {
  flex-shrink: 0;
  padding: 0 24px 16px;
  max-width: 740px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  background: #161A22;
  border: 1px solid #1F2937;
  border-radius: 12px;
  padding: 8px 8px 8px 4px;
  transition: border-color 0.2s;
}

.input-wrapper:focus-within {
  border-color: rgba(255, 255, 255, 0.2);
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.04);
}

/* ===== 输入框 ===== */
.input-box {
  flex: 1;
  font-size: 15px;
}

::v-deep .el-textarea__inner {
  border: none !important;
  border-radius: 0 !important;
  padding: 6px 8px;
  box-shadow: none !important;
  resize: none;
  font-family: 'Noto Sans SC', -apple-system, sans-serif;
  font-size: 15px;
  line-height: 1.5;
  background: transparent !important;
  color: #F1F5F9;
}

::v-deep .el-textarea__inner::placeholder {
  color: #64748B;
}

::v-deep .el-textarea__inner:focus {
  border: none !important;
  box-shadow: none !important;
}

/* ===== 输入框内图标按钮 ===== */
.input-icon-btn {
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #64748B;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.input-icon-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #94A3B8;
}

/* ===== 发送按钮 ===== */
.send-btn {
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 50%;
  background: #1F2937;
  color: #64748B;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: default;
  transition: all 0.2s;
  flex-shrink: 0;
}

.send-btn.has-text {
  background: #F1F5F9;
  color: #0C0F14;
  cursor: pointer;
}

.send-btn.has-text:hover {
  background: #FFFFFF;
  box-shadow: 0 4px 12px rgba(255, 255, 255, 0.1);
}

/* ===== 底部提示 ===== */
.input-footer {
  text-align: center;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 12px;
  color: #475569;
  padding-top: 8px;
}
</style>

<style>
/* ECharts 图表按钮（v-html 注入） */
.echart-btn {
  display: inline-block;
  padding: 8px 16px;
  background: #1F2937;
  color: #38BDF8;
  border: 1px solid #334155;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  margin: 8px 4px;
  transition: background 0.2s;
  font-family: inherit;
}
.echart-btn:hover {
  background: #334155;
}

/* 参考文献链接 */
.ref-link {
  color: #38BDF8 !important;
  text-decoration: none !important;
  border-bottom: 1px dashed rgba(56, 189, 248, 0.4);
  transition: all 0.2s;
  cursor: pointer;
}
.ref-link:hover {
  color: #7DD3FC !important;
  border-bottom-color: #38BDF8;
  background: rgba(56, 189, 248, 0.06);
  border-radius: 2px;
  padding: 0 2px;
}
.ref-link::after {
  content: ' 📄';
  font-size: 12px;
  opacity: 0.6;
}

/* 正文中的内联引用标注 [N] */
.inline-cite {
  color: #38BDF8;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.85em;
  vertical-align: super;
  text-decoration: none;
  transition: all 0.2s;
  padding: 0 1px;
  border-radius: 2px;
}
.inline-cite:hover {
  color: #7DD3FC;
  background: rgba(56, 189, 248, 0.12);
}

/* 进度条样式（不能 scoped，因为是 v-html 注入） */
.pipeline-progress {
  background: #111318;
  border: 1px solid #1F2937;
  border-radius: 10px;
  padding: 14px 16px 12px;
  margin-bottom: 8px;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
}

.progress-step {
  color: #94A3B8;
  padding: 3px 0;
  line-height: 1.6;
}

.progress-bar-wrap {
  margin-top: 10px;
  height: 4px;
  background: #1F2937;
  border-radius: 2px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #94A3B8, #CBD5E1);
  border-radius: 2px;
  transition: width 0.4s ease;
}

.progress-bar-complete {
  background: linear-gradient(90deg, #10B981, #34D399) !important;
}

.progress-pct {
  text-align: right;
  font-size: 11px;
  color: #64748B;
  margin-top: 4px;
  font-family: 'JetBrains Mono', monospace;
}

.progress-pct-done {
  text-align: right;
  font-size: 11px;
  color: #10B981;
  margin-top: 4px;
  font-weight: 500;
  font-family: 'JetBrains Mono', monospace;
}

/* Agent 详情展开面板 */
.agent-details {
  margin-top: 6px;
  margin-bottom: 4px;
}

.agent-details summary {
  cursor: pointer;
  color: #64748B;
  font-size: 12px;
  user-select: none;
  padding: 2px 0;
}

.agent-details summary:hover {
  color: #F1F5F9;
}

.agent-details-content {
  background: rgba(255, 255, 255, 0.02);
  border-left: 2px solid #374151;
  padding: 8px 12px;
  margin-top: 4px;
  font-size: 12px;
  color: #64748B;
  line-height: 1.7;
  border-radius: 0 4px 4px 0;
}

.agent-detail-item {
  padding: 2px 0;
}

.agent-detail-item .agent-name {
  color: #F1F5F9;
  font-weight: 600;
}

.agent-detail-item .tool-call {
  color: #A78BFA;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.agent-detail-item .tool-result {
  color: #34D399;
  font-size: 11px;
}

.agent-detail-item .agent-decision {
  color: #94A3B8;
  font-style: italic;
}

/* Agent 交互按钮 */
.agent-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #1F2937;
}

.agent-btn {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
  font-weight: 500;
  padding: 8px 20px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid #374151;
  background: rgba(255, 255, 255, 0.04);
  color: #CBD5E1;
}

.agent-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: #4B5563;
  color: #F1F5F9;
}

.agent-btn-primary {
  background: #F1F5F9;
  color: #0C0F14;
  border-color: #F1F5F9;
  font-weight: 600;
}

.agent-btn-primary:hover {
  background: #FFFFFF;
  box-shadow: 0 4px 12px rgba(255, 255, 255, 0.1);
}

.agent-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 引用悬浮气泡 */
.cite-tooltip {
  position: absolute;
  z-index: 9999;
  max-width: 380px;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 10px;
  padding: 12px 14px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.5);
  pointer-events: none;
  animation: tooltipFadeIn 0.15s ease-out;
}
@keyframes tooltipFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
.cite-tooltip-title {
  font-size: 12px;
  color: #60a5fa;
  font-weight: 600;
  margin-bottom: 6px;
}
.cite-tooltip-text {
  font-size: 13px;
  color: #cbd5e1;
  line-height: 1.6;
  word-break: break-word;
}
</style>
