<template>
  <div class="landing-container">
    <!-- 顶部导航 -->
    <header class="landing-header">
      <div class="header-left">
        <div class="header-logo">
          <span class="logo-mark"><img src="../assets/imgs/DeepCoke_logo.png" alt="DC" /></span>
          DeepCoke
          <span class="edition-badge">Enterprise</span>
        </div>
      </div>
      <div class="header-right">
        <span class="user-name">{{ userName }}</span>
        <button class="logout-btn" @click="logout">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
            <polyline points="16 17 21 12 16 7"/>
            <line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
          退出
        </button>
      </div>
    </header>

    <!-- 主内容区 -->
    <main class="landing-main">
      <!-- Hero 区域 -->
      <section class="hero-section">
        <div class="hero-badge">
          <span class="badge-dot"></span>
          焦化企业智能决策平台
        </div>
        <h1 class="hero-title">Deep<span class="title-accent">Coke</span></h1>
        <p class="hero-subtitle">焦化智能决策系统</p>
        <p class="hero-desc">6 大专业 Agent 协作 · 18+ 项 Skills · 闭环校验 · 自主决策<br/>通过 AI 多智能体优化配煤方案、预测焦炭质量、对接产线 DCS 系统</p>
        <div class="hero-stats">
          <div class="stat-item">
            <span class="stat-value">8</span>
            <span class="stat-label">预测模型</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-value">6017</span>
            <span class="stat-label">知识文档</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-value">6</span>
            <span class="stat-label">AI Agent</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-value">OPC-UA</span>
            <span class="stat-label">产线对接</span>
          </div>
        </div>
      </section>

      <!-- 四大产品卡片 - Bento Grid -->
      <section class="products-section">
        <div
          class="product-card"
          v-for="product in products"
          :key="product.id"
          :class="'card-' + product.id"
        >
          <div class="card-header">
            <div class="card-icon-wrapper" :style="{ background: product.gradient }">
              <i :class="product.icon" class="card-icon"></i>
            </div>
            <span class="card-status" :class="{ 'card-status-dev': product.status === '开发中' || product.status === '规划中' }">{{ product.status }}</span>
          </div>
          <h3 class="card-title">{{ product.title }}</h3>
          <p class="card-desc">{{ product.desc }}</p>
          <div class="card-tags">
            <span class="tag" v-for="tag in product.tags" :key="tag">{{ tag }}</span>
          </div>
        </div>
      </section>

      <!-- CTA 按钮 -->
      <section class="cta-section">
        <button class="cta-button" @click="enterChat">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          进入工作台
        </button>
        <p class="cta-hint">输入配煤需求或工艺问题，系统将自动调度多智能体生成方案</p>
      </section>

      <!-- 示例问题 -->
      <section class="capabilities-section">
        <h2 class="section-title">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          试着问这些问题
        </h2>
        <div class="examples-grid">
          <div class="example-item" v-for="(example, idx) in examples" :key="idx" @click="enterChatWithQuestion(example)">
            <span class="example-num">{{ String(idx + 1).padStart(2, '0') }}</span>
            <span class="example-text">{{ example }}</span>
            <svg class="example-arrow" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="5" y1="12" x2="19" y2="12"/>
              <polyline points="12 5 19 12 12 19"/>
            </svg>
          </div>
        </div>
      </section>
    </main>

    <!-- 底部 -->
    <footer class="landing-footer">
      <img class="footer-logo" src="../assets/imgs/CompanyLogo.png" alt="Logo" />
      <span class="footer-text">苏州龙泰氢一能源科技有限公司 · 企业版</span>
    </footer>
  </div>
</template>

<script>
export default {
  name: 'LandingPage',
  data () {
    return {
      userName: window.sessionStorage.getItem('nickname') || window.sessionStorage.getItem('username') || 'user',
      products: [
        {
          id: 'blend',
          icon: 'el-icon-s-operation',
          title: '配煤优化',
          desc: '企业级多目标配煤优化引擎，综合成本、质量、库存约束，自动生成最优配比方案，降本增效。',
          gradient: 'linear-gradient(135deg, #334155 0%, #64748B 100%)',
          tags: ['多目标优化', '成本分析', '质量管控'],
          status: '可用'
        },
        {
          id: 'twin',
          icon: 'el-icon-monitor',
          title: '数字孪生',
          desc: '基于 UE5 的焦炉三维实时监控，温度场可视化，支持 OPC-UA 协议对接现场数据。',
          gradient: 'linear-gradient(135deg, #0EA5E9 0%, #38BDF8 100%)',
          tags: ['三维监控', '温度场', 'OPC-UA'],
          status: '规划中'
        },
        {
          id: 'dcs',
          icon: 'el-icon-connection',
          title: '产线对接',
          desc: '通过 OPC-UA/Modbus 协议连接工厂 DCS/PLC 系统，实现配煤方案自动下发与执行。',
          gradient: 'linear-gradient(135deg, #64748B 0%, #94A3B8 100%)',
          tags: ['OPC-UA', 'Modbus', '自动执行'],
          status: '规划中'
        },
        {
          id: 'knowledge',
          icon: 'el-icon-notebook-2',
          title: '工艺知识库',
          desc: '企业焦化工艺知识库，涵盖文献检索、操作规程、故障诊断，为生产决策提供智能指导。',
          gradient: 'linear-gradient(135deg, #10B981 0%, #34D399 100%)',
          tags: ['文献检索', '知识图谱', 'RAG问答'],
          status: '可用'
        }
      ],
      examples: [
        '今日来煤灰分偏高，如何调整配比？',
        '当前焦炭CSR不达标，分析原因',
        '本月焦煤库存紧张，替代方案有哪些？',
        '焦炉温度场偏差超限，排查建议',
        '优化当前配比使吨焦成本降低5%',
        '近期焦炭M40指标波动大，如何稳定？'
      ]
    }
  },
  methods: {
    enterChat () {
      this.$router.push({ name: 'MainDia', params: { sessionId: 'new' } })
    },
    enterChatWithQuestion (question) {
      this.$router.push({
        name: 'MainDia',
        params: { sessionId: 'new' },
        query: { q: question }
      })
    },
    logout () {
      window.sessionStorage.removeItem('token')
      this.$router.push('/login')
    }
  }
}
</script>

<style lang="less" scoped>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Noto+Sans+SC:wght@300;400;500;600;700&display=swap');

@dark: #0C0F14;
@dark-elevated: #161A22;
@dark-card: #1A1F28;
@dark-border: #1F2937;
@accent: #E2E8F0;
@accent-dim: rgba(226, 232, 240, 0.08);
@cyan: #0EA5E9;
@text-bright: #F1F5F9;
@text-secondary: #94A3B8;
@text-muted: #64748B;

.landing-container {
  min-height: 100vh;
  background: @dark;
  position: relative;
  overflow-x: hidden;
  color: @text-bright;
}

/* 顶部导航 */
.landing-header {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  height: 48px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 28px;
  background: rgba(12, 15, 20, 0.8);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid @dark-border;
}

.header-left {
  display: flex;
  align-items: center;
}

.header-logo {
  font-family: 'JetBrains Mono', monospace;
  font-size: 15px;
  font-weight: 700;
  color: @text-bright;
  display: flex;
  align-items: center;
  gap: 8px;
}

.logo-mark {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: @text-bright;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;

  img {
    width: 18px;
    height: 18px;
    object-fit: contain;
  }
}

.edition-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  color: @accent;
  background: @accent-dim;
  border: 1px solid rgba(226, 232, 240, 0.25);
  padding: 1px 7px;
  border-radius: 4px;
  letter-spacing: 1px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.user-name {
  color: @text-muted;
  font-size: 12px;
  font-family: 'Noto Sans SC', sans-serif;
}

.logout-btn {
  background: transparent;
  border: 1px solid @dark-border;
  color: @text-muted;
  font-size: 12px;
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 4px;
  font-family: 'Noto Sans SC', sans-serif;

  &:hover {
    color: @text-bright;
    border-color: #374151;
  }
}

/* 主内容 */
.landing-main {
  position: relative;
  z-index: 1;
  max-width: 1060px;
  margin: 0 auto;
  padding: 80px 32px 40px;
}

/* Hero 区域 */
.hero-section {
  text-align: center;
  padding: 56px 0 36px;
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 18px;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 12px;
  color: @accent;
  background: @accent-dim;
  border: 1px solid rgba(226, 232, 240, 0.2);
  border-radius: 20px;
  margin-bottom: 28px;
  letter-spacing: 1.5px;
  font-weight: 500;
}

.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: @accent;
  animation: pulse-dot 2s infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(255, 255, 255, 0.4); }
  50% { opacity: 0.8; box-shadow: 0 0 0 6px rgba(255, 255, 255, 0); }
}

.hero-title {
  font-family: 'JetBrains Mono', monospace;
  font-size: 72px;
  font-weight: 700;
  color: @text-bright;
  margin: 0 0 8px;
  letter-spacing: 3px;
}

.title-accent {
  color: @accent;
}

.hero-subtitle {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 22px;
  color: @text-secondary;
  font-weight: 300;
  margin: 0 0 18px;
  letter-spacing: 8px;
}

.hero-desc {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 14px;
  color: @text-muted;
  line-height: 2;
  margin: 0 auto;
}

.hero-stats {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 36px;
  margin-top: 40px;
  padding: 22px 44px;
  background: @dark-elevated;
  border: 1px solid @dark-border;
  border-radius: 12px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.stat-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 26px;
  font-weight: 700;
  color: @text-bright;
}

.stat-label {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 11px;
  color: @text-muted;
  letter-spacing: 1px;
}

.stat-divider {
  width: 1px;
  height: 36px;
  background: @dark-border;
}

/* 产品卡片 */
.products-section {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  padding: 36px 0;
}

.product-card {
  background: @dark-card;
  border: 1px solid @dark-border;
  border-radius: 12px;
  padding: 24px 20px;
  transition: all 0.3s ease;
  cursor: pointer;

  &:hover {
    border-color: #374151;
    transform: translateY(-2px);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  }
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}

.card-icon-wrapper {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.card-icon {
  font-size: 22px;
  color: #fff;
}

.card-status {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  padding: 3px 10px;
  border-radius: 4px;
  background: @accent-dim;
  color: @accent;
  letter-spacing: 0.5px;
}

.card-status-dev {
  background: rgba(100, 116, 139, 0.15);
  color: @text-muted;
}

.card-title {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 16px;
  color: @text-bright;
  margin: 0 0 10px;
  font-weight: 600;
}

.card-desc {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
  color: @text-muted;
  line-height: 1.8;
  margin: 0 0 16px;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: @text-muted;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid @dark-border;
  padding: 3px 10px;
  border-radius: 4px;
}

/* CTA 按钮 */
.cta-section {
  text-align: center;
  padding: 20px 0 40px;
}

.cta-button {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 14px 44px;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 2px;
  color: @dark;
  background: @text-bright;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.3s ease;

  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 28px rgba(255, 255, 255, 0.12);
  }

  &:active {
    transform: translateY(0);
  }
}

.cta-hint {
  font-family: 'Noto Sans SC', sans-serif;
  margin-top: 16px;
  font-size: 13px;
  color: @text-muted;
}

/* 示例问题 */
.capabilities-section {
  padding: 16px 0 48px;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 15px;
  color: @text-secondary;
  font-weight: 400;
  margin: 0 0 24px;

  svg {
    opacity: 0.4;
  }
}

.examples-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.example-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: @dark-card;
  border: 1px solid @dark-border;
  border-radius: 10px;
  color: @text-secondary;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    background: @dark-elevated;
    border-color: #374151;
    color: @text-bright;

    .example-arrow {
      color: @accent;
      transform: translateX(3px);
    }

    .example-num {
      color: @accent;
    }
  }
}

.example-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: @text-muted;
  flex-shrink: 0;
  transition: color 0.2s;
}

.example-text {
  flex: 1;
}

.example-arrow {
  color: @text-muted;
  flex-shrink: 0;
  transition: all 0.2s;
}

/* 底部 */
.landing-footer {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px 0 32px;
  border-top: 1px solid @dark-border;
}

.footer-logo {
  width: 120px;
  height: auto;
  margin-bottom: 8px;
  opacity: 0.3;
  filter: grayscale(1) brightness(2);
}

.footer-text {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 12px;
  color: @text-muted;
  letter-spacing: 1px;
}

/* 响应式 */
@media (max-width: 900px) {
  .products-section {
    grid-template-columns: repeat(2, 1fr);
  }
  .hero-title {
    font-size: 48px;
  }
}

@media (max-width: 600px) {
  .products-section {
    grid-template-columns: 1fr;
  }
  .examples-grid {
    grid-template-columns: 1fr;
  }
  .hero-stats {
    flex-direction: column;
    gap: 16px;
  }
  .stat-divider {
    width: 32px;
    height: 1px;
  }
}
</style>
