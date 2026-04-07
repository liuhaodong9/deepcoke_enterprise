<template>
  <div class="data-panel">
    <!-- 上方：煤仓库列表 -->
    <div class="coal-table-section">
      <div class="section-header">
        <span class="section-title">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <ellipse cx="12" cy="5" rx="9" ry="3"/>
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
          </svg>
          煤仓库列表
        </span>
        <button class="refresh-btn" @click="fetchCoalData(currentPage)" title="刷新">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23 4 23 10 17 10"/>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
          </svg>
        </button>
      </div>
      <div class="table-wrapper">
        <el-table
          :data="coalData"
          size="mini"
          stripe
          border
          height="100%"
          :header-cell-style="{ background: '#F1F5F9', color: '#334155', fontSize: '12px', padding: '6px 0' }"
          :cell-style="{ fontSize: '12px', padding: '4px 0' }"
        >
          <el-table-column prop="coal_name" label="煤样名称" min-width="90" show-overflow-tooltip />
          <el-table-column prop="coal_type" label="煤种" min-width="65" show-overflow-tooltip />
          <el-table-column prop="coal_price" label="价格" min-width="55" align="right" />
          <el-table-column prop="coal_mad" label="Mad%" min-width="52" align="right" />
          <el-table-column prop="coal_ad" label="Ad%" min-width="48" align="right" />
          <el-table-column prop="coal_vdaf" label="Vdaf%" min-width="52" align="right" />
          <el-table-column prop="coal_std" label="St,d%" min-width="50" align="right" />
          <el-table-column prop="G" label="G" min-width="40" align="right" />
          <el-table-column prop="X" label="X" min-width="38" align="right" />
          <el-table-column prop="Y" label="Y" min-width="38" align="right" />
        </el-table>
      </div>
      <div class="pagination-wrapper">
        <el-pagination
          layout="total, prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page.sync="currentPage"
          @current-change="fetchCoalData"
          small
        />
      </div>
    </div>

    <!-- 下方：数字孪生视频 -->
    <div class="video-section">
      <div class="section-header">
        <span class="section-title">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
            <line x1="8" y1="21" x2="16" y2="21"/>
            <line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
          数字孪生
        </span>
      </div>
      <div class="video-wrapper">
        <video ref="twinVideo" muted playsinline preload="auto" class="twin-video">
          <source src="/static/数字孪生视频.mp4" type="video/mp4" />
        </video>
        <!-- 监控覆盖层 -->
        <div v-if="monitoringActive" class="monitoring-overlay">
          <div class="mon-header">
            <span class="mon-dot"></span>
            {{ monitoringOvenId }}号焦炉 · 实时监控
          </div>
          <div class="mon-data">
            <div class="mon-item">
              <span class="mon-label">炉温</span>
              <span class="mon-value">{{ monitoringTemp.toFixed(1) }}<small>°C</small></span>
            </div>
            <div class="mon-item">
              <span class="mon-label">炉压</span>
              <span class="mon-value">{{ monitoringPressure.toFixed(1) }}<small> kPa</small></span>
            </div>
            <div class="mon-item">
              <span class="mon-label">运行</span>
              <span class="mon-value">{{ monitoringElapsed }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'CoalDataPanel',
  data () {
    return {
      coalData: [],
      total: 0,
      currentPage: 1,
      pageSize: 10,
      apiBaseUrl: 'http://127.0.0.1:8000',
      // 监控状态
      monitoringActive: false,
      monitoringOvenId: '1',
      monitoringTemp: 1050,
      monitoringPressure: 12.5,
      monitoringStartTime: null,
      monitoringTimer: null
    }
  },
  computed: {
    monitoringElapsed () {
      if (!this.monitoringStartTime) return '00:00'
      const diff = Math.floor((Date.now() - this.monitoringStartTime) / 1000)
      const m = String(Math.floor(diff / 60)).padStart(2, '0')
      const s = String(diff % 60).padStart(2, '0')
      return `${m}:${s}`
    }
  },
  methods: {
    async fetchCoalData (page) {
      try {
        const res = await fetch(`${this.apiBaseUrl}/all_coals_page/?page=${page}&page_size=${this.pageSize}`)
        const json = await res.json()
        this.coalData = json.data || []
        this.total = json.total || 0
      } catch (e) {
        console.error('加载煤样数据失败:', e)
      }
    },
    handleVideoControl (cmd) {
      const video = this.$refs.twinVideo
      if (!video) return
      if (cmd === 'blend') {
        video.currentTime = 10
        video.loop = false
        video.play()
      } else if (cmd === 'stop') {
        video.pause()
      }
    },
    handleMonitoringControl ({ action, ovenId }) {
      if (action === 'start') {
        this.monitoringActive = true
        this.monitoringOvenId = ovenId || '1'
        this.monitoringTemp = 1050
        this.monitoringPressure = 12.5
        this.monitoringStartTime = Date.now()
        // 每秒更新模拟数据
        if (this.monitoringTimer) clearInterval(this.monitoringTimer)
        this.monitoringTimer = setInterval(() => {
          this.monitoringTemp += (Math.random() - 0.48) * 3
          this.monitoringTemp = Math.max(1000, Math.min(1100, this.monitoringTemp))
          this.monitoringPressure += (Math.random() - 0.48) * 0.5
          this.monitoringPressure = Math.max(10, Math.min(15, this.monitoringPressure))
          // 强制刷新 elapsed
          this.$forceUpdate()
        }, 1000)
      } else if (action === 'stop') {
        this.monitoringActive = false
        if (this.monitoringTimer) {
          clearInterval(this.monitoringTimer)
          this.monitoringTimer = null
        }
      }
    }
  },
  mounted () {
    this.fetchCoalData(1)
    this.$eventBus.$on('video-control', this.handleVideoControl)
    this.$eventBus.$on('monitoring-control', this.handleMonitoringControl)
    // 视频加载后停在第8秒
    this.$nextTick(() => {
      const video = this.$refs.twinVideo
      if (video) {
        video.currentTime = 10
        video.pause()
      }
    })
  },
  beforeDestroy () {
    this.$eventBus.$off('video-control', this.handleVideoControl)
    this.$eventBus.$off('monitoring-control', this.handleMonitoringControl)
    if (this.monitoringTimer) clearInterval(this.monitoringTimer)
  }
}
</script>

<style lang="less" scoped>
.data-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: #FAFBFC;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px 8px;
  flex-shrink: 0;
}

.section-title {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
  font-weight: 600;
  color: #1E293B;
  display: flex;
  align-items: center;
  gap: 6px;

  svg {
    color: #64748B;
  }
}

.refresh-btn {
  width: 28px;
  height: 28px;
  border: 1px solid #E2E8F0;
  border-radius: 6px;
  background: #FFFFFF;
  color: #64748B;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    color: #1E293B;
    border-color: #CBD5E1;
  }
}

/* 煤仓表格区域 */
.coal-table-section {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid #E2E8F0;
}

.table-wrapper {
  flex: 1;
  min-height: 0;
  padding: 0 14px;
}

.pagination-wrapper {
  padding: 8px 14px;
  flex-shrink: 0;
  display: flex;
  justify-content: center;
}

/* 视频区域 */
.video-section {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.video-wrapper {
  flex: 1;
  padding: 0 14px 14px;
  min-height: 0;
  position: relative;
}

.twin-video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  border-radius: 8px;
  background: #000;
}

/* ===== 监控覆盖层 ===== */
.monitoring-overlay {
  position: absolute;
  top: 0;
  left: 14px;
  right: 14px;
  bottom: 14px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding: 16px;
  pointer-events: none;
  z-index: 10;
}

.mon-header {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 14px;
  font-weight: 600;
  color: #FFFFFF;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.mon-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22C55E;
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.6);
  animation: pulse-dot 1.5s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.mon-data {
  display: flex;
  gap: 16px;
}

.mon-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.mon-label {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 10px;
  color: rgba(255, 255, 255, 0.6);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.mon-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 18px;
  font-weight: 600;
  color: #FFFFFF;

  small {
    font-size: 11px;
    font-weight: 400;
    color: rgba(255, 255, 255, 0.7);
  }
}
</style>
