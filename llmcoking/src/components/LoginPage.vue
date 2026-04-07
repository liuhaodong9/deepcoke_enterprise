<template>
  <div class="login_container">
    <!-- 左侧品牌展示区 -->
    <div class="brand-panel">
      <div class="brand-content">
        <div class="brand-badge">ENTERPRISE</div>
        <div class="brand-title-row">
          <div class="brand-logo-icon">
            <img src="../assets/imgs/DeepCoke_logo.png" alt="DeepCoke" />
          </div>
          <div class="brand-title-text">
            <h1 class="brand-logo">Deep<span class="logo-accent">Coke</span></h1>
            <p class="brand-tagline">焦化智能决策系统</p>
          </div>
        </div>
        <div class="brand-features">
          <div class="feature-item">
            <div class="feature-dot"></div>
            <span>6 大专业 Agent 协作</span>
          </div>
          <div class="feature-item">
            <div class="feature-dot"></div>
            <span>18+ 项 Skills 覆盖</span>
          </div>
          <div class="feature-item">
            <div class="feature-dot"></div>
            <span>闭环校验 · 自主决策</span>
          </div>
        </div>
      </div>
      <!-- 动态粒子背景 -->
      <canvas ref="particleCanvas" class="particle-canvas"></canvas>
      <!-- 装饰网格线 -->
      <div class="grid-overlay"></div>
      <!-- 底部公司信息 -->
      <div class="brand-footer">
        <img src="../assets/imgs/CompanyLogo.png" alt="Logo" class="brand-footer-logo" />
        <span>苏州龙泰氢一能源科技有限公司</span>
      </div>
    </div>

    <!-- 右侧登录区 -->
    <div class="auth-panel">
      <div class="login_box">
        <!-- Tab 切换 -->
        <div class="tab-switch">
          <span :class="{ active: mode === 'login' }" @click="switchMode('login')">登录</span>
          <span :class="{ active: mode === 'register' }" @click="switchMode('register')">注册</span>
        </div>

        <!-- ===== 登录表单 ===== -->
        <el-form
          v-show="mode === 'login'"
          ref="loginFormRef"
          :model="loginForm"
          :rules="loginFormRules"
          label-width="0px"
          class="auth-form"
          @keyup.enter.native="login"
        >
          <el-form-item prop="username">
            <el-input v-model="loginForm.username" placeholder="用户账号" prefix-icon="el-icon-user-solid"></el-input>
          </el-form-item>
          <el-form-item prop="password">
            <el-input v-model="loginForm.password" placeholder="用户密码" prefix-icon="el-icon-lock" show-password auto-complete="new-password"></el-input>
          </el-form-item>
          <div class="form-options">
            <label class="user-agreement">
              <input type="checkbox" v-model="agreeToTerms" />
              阅读并接受
              <a href="#" @click.prevent>用户协议</a>和<a href="#" @click.prevent>隐私政策</a>
            </label>
            <a href="#" class="forgot-link" @click.prevent="forgotPassword">忘记密码？</a>
          </div>
          <button class="submit-btn" :disabled="loginLoading" @click.prevent="login">
            <span v-if="!loginLoading">进 入 系 统</span>
            <span v-else class="btn-loading">
              <span class="spinner"></span> 登录中...
            </span>
          </button>
          <div class="switch-link">
            还没有账号？<a href="#" @click.prevent="switchMode('register')">立即注册</a>
          </div>
        </el-form>

        <!-- ===== 注册表单 ===== -->
        <el-form
          v-show="mode === 'register'"
          ref="registerFormRef"
          :model="registerForm"
          :rules="registerFormRules"
          label-width="0px"
          class="auth-form"
          @keyup.enter.native="register"
        >
          <el-form-item prop="username">
            <el-input v-model="registerForm.username" placeholder="设置用户账号（3-10个字符）" prefix-icon="el-icon-user-solid"></el-input>
          </el-form-item>
          <el-form-item prop="nickname">
            <el-input v-model="registerForm.nickname" placeholder="设置昵称（选填）" prefix-icon="el-icon-s-custom"></el-input>
          </el-form-item>
          <el-form-item prop="password">
            <el-input v-model="registerForm.password" placeholder="设置密码（6-15个字符）" prefix-icon="el-icon-lock" show-password></el-input>
          </el-form-item>
          <el-form-item prop="confirmPassword">
            <el-input v-model="registerForm.confirmPassword" placeholder="确认密码" prefix-icon="el-icon-lock" show-password></el-input>
          </el-form-item>
          <div class="form-options">
            <label class="user-agreement">
              <input type="checkbox" v-model="agreeToTermsReg" />
              阅读并接受
              <a href="#" @click.prevent>用户协议</a>和<a href="#" @click.prevent>隐私政策</a>
            </label>
          </div>
          <button class="submit-btn" :disabled="registerLoading" @click.prevent="register">
            <span v-if="!registerLoading">注 册</span>
            <span v-else class="btn-loading">
              <span class="spinner"></span> 注册中...
            </span>
          </button>
          <div class="switch-link">
            已有账号？<a href="#" @click.prevent="switchMode('login')">返回登录</a>
          </div>
        </el-form>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  data () {
    const validateConfirmPassword = (rule, value, callback) => {
      if (value !== this.registerForm.password) {
        callback(new Error('两次输入的密码不一致'))
      } else {
        callback()
      }
    }

    return {
      mode: 'login',
      agreeToTerms: false,
      agreeToTermsReg: false,
      loginLoading: false,
      registerLoading: false,
      apiBaseUrl: 'http://127.0.0.1:8000',

      loginForm: { username: '', password: '' },
      loginFormRules: {
        username: [
          { required: true, message: '请输入登录账号', trigger: 'blur' },
          { min: 3, max: 10, message: '长度在 3 到 10 个字符', trigger: 'blur' }
        ],
        password: [
          { required: true, message: '请输入登录密码', trigger: 'blur' },
          { min: 6, max: 15, message: '长度在 6 到 15 个字符', trigger: 'blur' }
        ]
      },

      registerForm: { username: '', nickname: '', password: '', confirmPassword: '' },
      registerFormRules: {
        username: [
          { required: true, message: '请设置用户账号', trigger: 'blur' },
          { min: 3, max: 10, message: '长度在 3 到 10 个字符', trigger: 'blur' }
        ],
        password: [
          { required: true, message: '请设置密码', trigger: 'blur' },
          { min: 6, max: 15, message: '长度在 6 到 15 个字符', trigger: 'blur' }
        ],
        confirmPassword: [
          { required: true, message: '请确认密码', trigger: 'blur' },
          { validator: validateConfirmPassword, trigger: 'blur' }
        ]
      }
    }
  },
  methods: {
    switchMode (newMode) {
      this.mode = newMode
    },
    login () {
      this.$refs.loginFormRef.validate(async (valid) => {
        if (!valid) return
        if (!this.agreeToTerms) {
          this.$message.warning('请先阅读并接受用户协议和隐私政策')
          return
        }

        this.loginLoading = true
        try {
          const res = await this.$http.post(`${this.apiBaseUrl}/login`, this.loginForm)
          if (res.status !== 200 || res.data === 'fail') {
            this.$message.error('用户名或密码错误！')
            return
          }

          this.$message.success('登录成功！')
          window.sessionStorage.setItem('token', res.data.token)
          window.sessionStorage.setItem('username', res.data.username)
          window.sessionStorage.setItem('nickname', res.data.nickname || res.data.username)

          this.$router.push({ name: 'Landing' })
        } catch (error) {
          this.$message.error('网络错误，请检查后端是否启动')
        } finally {
          this.loginLoading = false
        }
      })
    },
    register () {
      this.$refs.registerFormRef.validate(async (valid) => {
        if (!valid) return
        if (!this.agreeToTermsReg) {
          this.$message.warning('请先阅读并接受用户协议和隐私政策')
          return
        }

        this.registerLoading = true
        try {
          const res = await this.$http.post(`${this.apiBaseUrl}/register`, {
            username: this.registerForm.username,
            password: this.registerForm.password,
            nickname: this.registerForm.nickname
          })

          if (res.data.status === 'ok') {
            this.$message.success('注册成功，请登录！')
            this.loginForm.username = this.registerForm.username
            this.loginForm.password = ''
            this.mode = 'login'
          } else {
            this.$message.error(res.data.message || '注册失败')
          }
        } catch (error) {
          this.$message.error('网络错误，请稍后重试')
        } finally {
          this.registerLoading = false
        }
      })
    },
    forgotPassword () {
      this.$message.info('请联系管理员重置密码')
    },
    initParticles () {
      const canvas = this.$refs.particleCanvas
      if (!canvas) return
      const ctx = canvas.getContext('2d')
      let w, h, particles
      const mouse = { x: -9999, y: -9999 }
      const MOUSE_RADIUS = 150
      const LINK_DIST = 100
      const MOUSE_LINK_DIST = 180

      const resize = () => {
        const rect = canvas.parentElement.getBoundingClientRect()
        w = canvas.width = rect.width
        h = canvas.height = rect.height
      }

      const createParticles = () => {
        const count = Math.floor((w * h) / 4000)
        particles = []
        for (let i = 0; i < count; i++) {
          particles.push({
            x: Math.random() * w,
            y: Math.random() * h,
            vx: (Math.random() - 0.5) * 0.3,
            vy: (Math.random() - 0.5) * 0.3,
            r: Math.random() * 1.2 + 0.4
          })
        }
      }

      // 鼠标跟踪
      const onMouseMove = (e) => {
        const rect = canvas.getBoundingClientRect()
        mouse.x = e.clientX - rect.left
        mouse.y = e.clientY - rect.top
      }
      const onMouseLeave = () => {
        mouse.x = -9999
        mouse.y = -9999
      }
      canvas.parentElement.addEventListener('mousemove', onMouseMove)
      canvas.parentElement.addEventListener('mouseleave', onMouseLeave)
      this._particleMouseMove = onMouseMove
      this._particleMouseLeave = onMouseLeave

      const draw = () => {
        ctx.clearRect(0, 0, w, h)

        // 更新位置 + 鼠标交互
        for (const p of particles) {
          // 鼠标吸引
          const dmx = mouse.x - p.x
          const dmy = mouse.y - p.y
          const dmd = Math.sqrt(dmx * dmx + dmy * dmy)
          if (dmd < MOUSE_RADIUS && dmd > 1) {
            const force = (MOUSE_RADIUS - dmd) / MOUSE_RADIUS * 0.02
            p.vx += dmx / dmd * force
            p.vy += dmy / dmd * force
          }

          // 速度阻尼
          p.vx *= 0.99
          p.vy *= 0.99

          // 限速
          const speed = Math.sqrt(p.vx * p.vx + p.vy * p.vy)
          if (speed > 1.5) {
            p.vx = p.vx / speed * 1.5
            p.vy = p.vy / speed * 1.5
          }

          p.x += p.vx
          p.y += p.vy
          if (p.x < 0) { p.x = 0; p.vx *= -1 }
          if (p.x > w) { p.x = w; p.vx *= -1 }
          if (p.y < 0) { p.y = 0; p.vy *= -1 }
          if (p.y > h) { p.y = h; p.vy *= -1 }
        }

        // 画粒子之间连线
        for (let i = 0; i < particles.length; i++) {
          for (let j = i + 1; j < particles.length; j++) {
            const dx = particles[i].x - particles[j].x
            const dy = particles[i].y - particles[j].y
            const dist = Math.sqrt(dx * dx + dy * dy)
            if (dist < LINK_DIST) {
              ctx.beginPath()
              ctx.moveTo(particles[i].x, particles[i].y)
              ctx.lineTo(particles[j].x, particles[j].y)
              ctx.strokeStyle = `rgba(0, 0, 0, ${0.1 * (1 - dist / LINK_DIST)})`
              ctx.lineWidth = 0.6
              ctx.stroke()
            }
          }
        }

        // 画鼠标到粒子的连线
        if (mouse.x > 0 && mouse.y > 0) {
          for (const p of particles) {
            const dx = mouse.x - p.x
            const dy = mouse.y - p.y
            const dist = Math.sqrt(dx * dx + dy * dy)
            if (dist < MOUSE_LINK_DIST) {
              ctx.beginPath()
              ctx.moveTo(mouse.x, mouse.y)
              ctx.lineTo(p.x, p.y)
              ctx.strokeStyle = `rgba(0, 0, 0, ${0.2 * (1 - dist / MOUSE_LINK_DIST)})`
              ctx.lineWidth = 0.8
              ctx.stroke()
            }
          }
        }

        // 画粒子
        for (const p of particles) {
          // 离鼠标近的粒子更亮更大
          const dmx = mouse.x - p.x
          const dmy = mouse.y - p.y
          const dmd = Math.sqrt(dmx * dmx + dmy * dmy)
          let alpha = 0.3
          let radius = p.r
          if (dmd < MOUSE_RADIUS) {
            const factor = 1 - dmd / MOUSE_RADIUS
            alpha = 0.3 + factor * 0.5
            radius = p.r + factor * 1.5
          }
          ctx.beginPath()
          ctx.arc(p.x, p.y, radius, 0, Math.PI * 2)
          ctx.fillStyle = `rgba(0, 0, 0, ${alpha})`
          ctx.fill()
        }

        this._particleAnimId = requestAnimationFrame(draw)
      }

      resize()
      createParticles()
      draw()

      this._particleResizeCreate = () => { resize(); createParticles() }
      window.addEventListener('resize', this._particleResizeCreate)
    }
  },
  mounted () {
    this.$nextTick(() => this.initParticles())
  },
  beforeDestroy () {
    if (this._particleAnimId) cancelAnimationFrame(this._particleAnimId)
    if (this._particleResizeCreate) window.removeEventListener('resize', this._particleResizeCreate)
    const canvas = this.$refs.particleCanvas
    if (canvas && canvas.parentElement) {
      if (this._particleMouseMove) canvas.parentElement.removeEventListener('mousemove', this._particleMouseMove)
      if (this._particleMouseLeave) canvas.parentElement.removeEventListener('mouseleave', this._particleMouseLeave)
    }
  }
}
</script>

<style lang="less" scoped>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Noto+Sans+SC:wght@300;400;500;600;700&display=swap');

@dark: #F1F5F9;
@dark-card: #FFFFFF;
@dark-border: #E2E8F0;
@accent: #1E293B;
@accent-dim: rgba(30, 41, 59, 0.06);
@text-bright: #1E293B;
@text-dim: #64748B;
@text-muted: #94A3B8;

.login_container {
  display: flex;
  height: 100vh;
  background: @dark;
  overflow: hidden;
}

/* ===== 左侧品牌面板 ===== */
.brand-panel {
  flex: 1;
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  padding: 60px;
  overflow: hidden;
  background:
    radial-gradient(ellipse 80% 60% at 20% 80%, rgba(0, 0, 0, 0.03) 0%, transparent 60%),
    radial-gradient(ellipse 60% 40% at 70% 20%, rgba(0, 0, 0, 0.02) 0%, transparent 50%),
    @dark;
}

.particle-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1;
}

.grid-overlay {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(0,0,0,0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,0,0,0.04) 1px, transparent 1px);
  background-size: 60px 60px;
  pointer-events: none;
  z-index: 0;
}

.brand-content {
  position: relative;
  z-index: 2;
  text-align: left;
  max-width: 420px;
}

.brand-badge {
  display: inline-block;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 3px;
  color: @accent;
  background: @accent-dim;
  border: 1px solid rgba(0, 0, 0, 0.12);
  padding: 4px 14px;
  border-radius: 4px;
  margin-bottom: 28px;
}

.brand-title-row {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 48px;
}

.brand-logo-icon {
  flex-shrink: 0;

  img {
    height: 90px;
    width: auto;
    object-fit: contain;
  }
}

.brand-title-text {
  display: flex;
  flex-direction: column;
}

.brand-logo {
  font-family: 'JetBrains Mono', monospace;
  font-size: 56px;
  font-weight: 700;
  color: @text-bright;
  margin: 0;
  letter-spacing: 2px;
  line-height: 1;
}

.logo-accent {
  color: @accent;
}

.brand-tagline {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 16px;
  color: @text-dim;
  font-weight: 300;
  letter-spacing: 4px;
  margin: 8px 0 0;
}

.brand-features {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 12px;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 14px;
  color: @text-dim;
  font-weight: 400;
}

.feature-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: @accent;
  flex-shrink: 0;
  box-shadow: 0 0 8px rgba(0, 0, 0, 0.2);
}

.brand-footer {
  position: absolute;
  bottom: 32px;
  left: 60px;
  display: flex;
  align-items: center;
  gap: 12px;
  z-index: 2;

  img {
    height: 28px;
    width: auto;
    opacity: 0.4;
    filter: grayscale(1) brightness(0.6);
  }

  span {
    font-size: 12px;
    color: @text-muted;
    letter-spacing: 1px;
  }
}

/* ===== 右侧登录面板 ===== */
.auth-panel {
  width: 480px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: @dark-card;
  border-left: 1px solid @dark-border;
}

.login_box {
  width: 100%;
  padding: 48px 48px 40px;
}

/* ===== Tab 切换 ===== */
.tab-switch {
  display: flex;
  gap: 0;
  margin-bottom: 36px;
  border-bottom: 1px solid @dark-border;

  span {
    flex: 1;
    text-align: center;
    padding: 12px 0;
    font-family: 'Noto Sans SC', sans-serif;
    font-size: 15px;
    color: @text-muted;
    cursor: pointer;
    transition: all 0.3s;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;

    &.active {
      color: @text-bright;
      font-weight: 600;
      border-bottom-color: @accent;
    }

    &:hover:not(.active) {
      color: @text-dim;
    }
  }
}

/* ===== 表单 ===== */
.auth-form {
  padding: 0;
}

::v-deep .el-input__inner {
  background: rgba(0, 0, 0, 0.02);
  border: 1px solid @dark-border;
  color: @text-bright;
  border-radius: 8px;
  height: 46px;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 14px;
  transition: all 0.2s;

  &::placeholder {
    color: @text-muted;
  }

  &:focus {
    border-color: rgba(0, 0, 0, 0.2);
    background: rgba(0, 0, 0, 0.03);
    box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.04);
  }
}

::v-deep .el-input__prefix {
  color: @text-muted;
}

/* 选项行 */
.form-options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.user-agreement {
  font-size: 12px;
  color: @text-muted;
  display: flex;
  align-items: center;
  cursor: pointer;
  font-family: 'Noto Sans SC', sans-serif;

  input[type="checkbox"] {
    margin-right: 6px;
    accent-color: @accent;
  }

  a {
    color: @accent;
    text-decoration: none;
    margin: 0 2px;
  }
}

.forgot-link {
  font-size: 12px;
  color: @text-dim;
  text-decoration: none;
  white-space: nowrap;
  font-family: 'Noto Sans SC', sans-serif;

  &:hover {
    color: @accent;
  }
}

/* 提交按钮 */
.submit-btn {
  width: 100%;
  height: 48px;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 4px;
  border-radius: 8px;
  border: none;
  color: @dark;
  background: @text-bright;
  cursor: pointer;
  transition: all 0.3s;
  margin-bottom: 20px;
  position: relative;
  overflow: hidden;

  &:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  }

  &:active:not(:disabled) {
    transform: translateY(0);
  }

  &:disabled {
    opacity: 0.7;
    cursor: wait;
  }
}

.btn-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  letter-spacing: 1px;
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(241, 245, 249, 0.3);
  border-top-color: @dark;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 切换链接 */
.switch-link {
  text-align: center;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
  color: @text-muted;

  a {
    color: @accent;
    text-decoration: none;
    margin-left: 4px;

    &:hover {
      text-decoration: underline;
    }
  }
}

/* 表单验证 */
::v-deep .el-form-item__error {
  color: #EF4444 !important;
  font-weight: 400 !important;
  font-size: 12px;
}

::v-deep .el-form-item {
  margin-bottom: 20px;
}

/* 响应式 */
@media (max-width: 960px) {
  .brand-panel {
    display: none;
  }
  .auth-panel {
    width: 100%;
  }
}
</style>
