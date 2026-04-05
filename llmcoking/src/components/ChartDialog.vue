<template>
  <el-dialog
    :visible.sync="visible"
    :title="chartTitle"
    width="70%"
    custom-class="chart-dialog"
    @opened="renderChart"
    @closed="disposeChart"
    append-to-body
  >
    <div ref="chartContainer" class="chart-container" :style="{ height: chartHeight }"></div>
  </el-dialog>
</template>

<script>
import * as echarts from 'echarts'

// 深色主题色板
const C = {
  bg: '#0C0F14',
  cardBg: '#161A22',
  border: '#334155',
  label: '#94A3B8',
  text: '#E2E8F0',
  grid: '#1F2937',
  cyan: '#38BDF8',
  green: '#10B981',
  gold: '#F59E0B',
  red: '#EF4444',
  purple: '#8B5CF6'
}

export default {
  data () {
    return {
      visible: false,
      chartData: null,
      chartTitle: '',
      chartHeight: '450px',
      chartInstance: null
    }
  },
  methods: {
    open (descriptor) {
      this.chartData = descriptor
      this.chartTitle = descriptor.title || '图表'
      this.chartHeight = descriptor.chartType === 'blend_dashboard' ? '520px' : '450px'
      this.visible = true
    },
    renderChart () {
      if (!this.chartData || !this.$refs.chartContainer) return
      this.chartInstance = echarts.init(this.$refs.chartContainer, null, {
        renderer: 'canvas'
      })
      let option = null
      switch (this.chartData.chartType) {
        case 'scatter':
          option = this.buildScatter(this.chartData)
          break
        case 'histogram':
          option = this.buildHistogram(this.chartData)
          break
        case 'pie':
          option = this.buildPie(this.chartData)
          break
        case 'radar':
          option = this.buildRadar(this.chartData)
          break
        case 'blend_dashboard':
          option = this.buildBlendDashboard(this.chartData)
          break
        case 'bar':
          option = this.buildBar(this.chartData)
          break
        case 'line':
          option = this.buildLine(this.chartData)
          break
      }
      if (option) {
        this.chartInstance.setOption(option)
      }
      // 响应弹窗 resize
      window.addEventListener('resize', this.handleResize)
    },
    handleResize () {
      if (this.chartInstance) this.chartInstance.resize()
    },
    disposeChart () {
      window.removeEventListener('resize', this.handleResize)
      if (this.chartInstance) {
        this.chartInstance.dispose()
        this.chartInstance = null
      }
    },

    // ── 散点图 ──
    buildScatter (desc) {
      const data = desc.data || []
      return {
        backgroundColor: C.bg,
        tooltip: {
          trigger: 'item',
          formatter: p => {
            const d = p.data
            return `<b>${d[2]}</b><br/>CRI: ${d[0]}<br/>CSR: ${d[1]}`
          }
        },
        visualMap: {
          min: Math.min(...data.map(d => d.csr)),
          max: Math.max(...data.map(d => d.csr)),
          dimension: 1,
          inRange: { color: ['#3B82F6', '#EF4444'] },
          textStyle: { color: C.label },
          right: 10
        },
        xAxis: {
          name: desc.xLabel || 'CRI',
          nameTextStyle: { color: C.label },
          axisLine: { lineStyle: { color: C.border } },
          axisLabel: { color: C.label },
          splitLine: { lineStyle: { color: C.grid, type: 'dashed' } }
        },
        yAxis: {
          name: desc.yLabel || 'CSR',
          nameTextStyle: { color: C.label },
          axisLine: { lineStyle: { color: C.border } },
          axisLabel: { color: C.label },
          splitLine: { lineStyle: { color: C.grid, type: 'dashed' } }
        },
        series: [{
          type: 'scatter',
          symbolSize: 8,
          data: data.map(d => [d.cri, d.csr, d.name]),
          itemStyle: { borderColor: C.border, borderWidth: 0.5 }
        }]
      }
    },

    // ── 直方图（5 个子图并排） ──
    buildHistogram (desc) {
      const metrics = desc.metrics || {}
      const labels = Object.keys(metrics)
      if (!labels.length) return null

      const colors = [C.cyan, C.green, C.gold, C.red, C.purple]
      const n = labels.length

      // 辅助：对一组值做分箱
      const buildBins = (vals) => {
        if (!vals || !vals.length) return { categories: [], counts: [], mean: 0 }
        const min = Math.min(...vals)
        const max = Math.max(...vals)
        const binCount = 15
        const binWidth = (max - min) / binCount || 1
        const bins = Array(binCount).fill(0)
        const categories = []
        for (let i = 0; i < binCount; i++) {
          categories.push((min + i * binWidth).toFixed(1))
        }
        vals.forEach(v => {
          let idx = Math.floor((v - min) / binWidth)
          if (idx >= binCount) idx = binCount - 1
          if (idx < 0) idx = 0
          bins[idx]++
        })
        const mean = vals.reduce((a, b) => a + b, 0) / vals.length
        return { categories, counts: bins, mean }
      }

      // 构建多 grid 布局
      const grids = []
      const xAxes = []
      const yAxes = []
      const series = []
      const titles = []
      const gap = 100 / n

      labels.forEach((label, i) => {
        const left = `${i * gap + 2}%`
        const width = `${gap - 4}%`
        grids.push({ left, width, top: 60, bottom: 40 })
        const d = buildBins(metrics[label])
        xAxes.push({
          type: 'category',
          gridIndex: i,
          data: d.categories,
          axisLabel: { color: C.label, fontSize: 8, rotate: 30 },
          axisLine: { lineStyle: { color: C.border } }
        })
        yAxes.push({
          gridIndex: i,
          axisLabel: { color: C.label, fontSize: 8 },
          axisLine: { lineStyle: { color: C.border } },
          splitLine: { lineStyle: { color: C.grid, type: 'dashed' } }
        })
        // 找到均值所在的 bin 索引
        const meanBinIdx = d.categories.findIndex((c, ci) => {
          const lo = parseFloat(c)
          const hi = ci < d.categories.length - 1 ? parseFloat(d.categories[ci + 1]) : Infinity
          return d.mean >= lo && d.mean < hi
        })
        series.push({
          type: 'bar',
          xAxisIndex: i,
          yAxisIndex: i,
          data: d.counts,
          itemStyle: { color: colors[i % colors.length] },
          markLine: {
            silent: true,
            data: meanBinIdx >= 0 ? [{ xAxis: meanBinIdx }] : [],
            label: { color: C.text, fontSize: 9, formatter: `\u03bc=${d.mean.toFixed(1)}` },
            lineStyle: { color: C.text, type: 'dashed' }
          }
        })
        titles.push({
          text: label,
          left: `${i * gap + gap / 2}%`,
          top: 30,
          textAlign: 'center',
          textStyle: { color: C.text, fontSize: 11, fontWeight: 'bold' }
        })
      })

      // 总标题
      titles.unshift({
        text: desc.title,
        left: 'center',
        top: 5,
        textStyle: { color: C.text, fontSize: 14, fontWeight: 'bold' }
      })

      return {
        backgroundColor: C.bg,
        title: titles,
        tooltip: { trigger: 'axis' },
        grid: grids,
        xAxis: xAxes,
        yAxis: yAxes,
        series
      }
    },

    // ── 饼图 ──
    buildPie (desc) {
      return {
        backgroundColor: C.bg,
        tooltip: {
          trigger: 'item',
          formatter: '{b}: {c} ({d}%)'
        },
        series: [{
          type: 'pie',
          radius: ['30%', '65%'],
          center: ['50%', '55%'],
          data: desc.data || [],
          label: {
            color: C.text,
            fontSize: 12
          },
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowOffsetX: 0,
              shadowColor: 'rgba(0, 0, 0, 0.5)'
            }
          }
        }]
      }
    },

    // ── 配煤方案仪表盘（饼图 + 仪表盘） ──
    buildBlendDashboard (desc) {
      const pieData = desc.pieData || []
      const predictions = desc.predictions || {}
      const constraints = desc.constraints || {}
      const costPerTon = desc.costPerTon || 0
      const model = desc.recommended_model || ''
      const passed = desc.passed

      const pieColors = [C.cyan, C.green, C.gold, C.red, C.purple, '#EC4899', '#14B8A6', '#F97316', '#6366F1', '#84CC16']

      const series = []
      const titles = [
        {
          text: desc.title + (passed ? ' ✅ 达标' : ' ⚠️ 不达标'),
          left: 'center',
          top: 5,
          textStyle: { color: C.text, fontSize: 16, fontWeight: 'bold' }
        },
        {
          text: '配煤比例',
          left: '25%',
          top: 35,
          textAlign: 'center',
          textStyle: { color: C.label, fontSize: 13 }
        }
      ]

      // 饼图（左侧）
      series.push({
        type: 'pie',
        radius: ['22%', '48%'],
        center: ['25%', '58%'],
        data: pieData.map((d, i) => ({
          ...d,
          itemStyle: { color: pieColors[i % pieColors.length] }
        })),
        label: {
          color: C.text,
          fontSize: 11,
          formatter: '{b}\n{d}%'
        },
        emphasis: {
          itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' }
        }
      })

      // 仪表盘（右侧）— CRI 和 CSR
      const gaugeItems = []
      if (predictions.CRI != null) {
        const criMax = constraints.CRI_max || 35
        gaugeItems.push({
          name: 'CRI (热反应性)',
          value: predictions.CRI,
          min: 15,
          max: 45,
          center: ['62%', '55%'],
          // CRI 越低越好：绿色区域在目标以下，红色在上
          colors: [[criMax / 45, C.green], [1, C.red]],
          constraint: criMax,
          constraintLabel: `上限≤${criMax}`
        })
      }
      if (predictions.CSR != null) {
        const csrMin = constraints.CSR_min || 60
        gaugeItems.push({
          name: 'CSR (热强度)',
          value: predictions.CSR,
          min: 40,
          max: 80,
          center: ['88%', '55%'],
          // CSR 越高越好：红色区域在目标以下，绿色在上
          colors: [[csrMin / 80, C.red], [1, C.green]],
          constraint: csrMin,
          constraintLabel: `下限≥${csrMin}`
        })
      }

      gaugeItems.forEach((g, idx) => {
        titles.push({
          text: g.name,
          left: g.center[0],
          top: 35,
          textAlign: 'center',
          textStyle: { color: C.label, fontSize: 12 }
        })
        series.push({
          type: 'gauge',
          center: g.center,
          radius: '32%',
          min: g.min,
          max: g.max,
          splitNumber: 6,
          axisLine: {
            lineStyle: {
              width: 12,
              color: g.colors
            }
          },
          pointer: {
            width: 4,
            length: '60%',
            itemStyle: { color: C.text }
          },
          axisTick: { show: true, lineStyle: { color: C.label, width: 1 }, length: 6 },
          splitLine: { length: 10, lineStyle: { color: C.label, width: 1 } },
          axisLabel: { color: C.label, fontSize: 9, distance: 15 },
          detail: {
            formatter: '{value}',
            color: C.text,
            fontSize: 20,
            fontWeight: 'bold',
            offsetCenter: [0, '75%']
          },
          title: {
            show: true,
            offsetCenter: [0, '95%'],
            color: C.gold,
            fontSize: 10
          },
          data: [{ value: g.value, name: g.constraintLabel }]
        })
      })

      // 底部成本信息
      const graphic = []
      if (costPerTon > 0) {
        graphic.push({
          type: 'text',
          left: 'center',
          bottom: 10,
          style: {
            text: `吨煤成本: ${costPerTon.toFixed(1)} 元/吨  |  推荐模型: ${model}`,
            fill: C.gold,
            fontSize: 13,
            fontWeight: 'bold'
          }
        })
      }

      return {
        backgroundColor: C.bg,
        title: titles,
        tooltip: { trigger: 'item' },
        series,
        graphic
      }
    },

    // ── 柱状图（LLM 文献数据可视化） ──
    buildBar (desc) {
      const categories = desc.categories || []
      const seriesData = desc.series || []
      const colors = [C.cyan, C.green, C.gold, C.red, C.purple]
      return {
        backgroundColor: C.bg,
        tooltip: { trigger: 'axis' },
        legend: {
          data: seriesData.map(s => s.name),
          textStyle: { color: C.label },
          top: 5
        },
        grid: { left: 60, right: 30, top: 50, bottom: 40 },
        xAxis: {
          type: 'category',
          data: categories,
          axisLabel: { color: C.label, fontSize: 11, rotate: categories.length > 6 ? 30 : 0 },
          axisLine: { lineStyle: { color: C.border } }
        },
        yAxis: {
          type: 'value',
          name: desc.yLabel || '',
          nameTextStyle: { color: C.label },
          axisLabel: { color: C.label },
          axisLine: { lineStyle: { color: C.border } },
          splitLine: { lineStyle: { color: C.grid, type: 'dashed' } }
        },
        series: seriesData.map((s, i) => ({
          name: s.name,
          type: 'bar',
          data: s.data,
          itemStyle: { color: colors[i % colors.length] },
          barMaxWidth: 40
        }))
      }
    },

    // ── 折线图（LLM 文献数据可视化） ──
    buildLine (desc) {
      const categories = desc.categories || []
      const seriesData = desc.series || []
      const colors = [C.cyan, C.green, C.gold, C.red, C.purple]
      return {
        backgroundColor: C.bg,
        tooltip: { trigger: 'axis' },
        legend: {
          data: seriesData.map(s => s.name),
          textStyle: { color: C.label },
          top: 5
        },
        grid: { left: 60, right: 30, top: 50, bottom: 40 },
        xAxis: {
          type: 'category',
          data: categories,
          name: desc.xLabel || '',
          nameTextStyle: { color: C.label },
          axisLabel: { color: C.label, fontSize: 11 },
          axisLine: { lineStyle: { color: C.border } }
        },
        yAxis: {
          type: 'value',
          name: desc.yLabel || '',
          nameTextStyle: { color: C.label },
          axisLabel: { color: C.label },
          axisLine: { lineStyle: { color: C.border } },
          splitLine: { lineStyle: { color: C.grid, type: 'dashed' } }
        },
        series: seriesData.map((s, i) => ({
          name: s.name,
          type: 'line',
          data: s.data,
          smooth: true,
          lineStyle: { color: colors[i % colors.length], width: 2 },
          itemStyle: { color: colors[i % colors.length] },
          areaStyle: { color: colors[i % colors.length] + '20' }
        }))
      }
    },

    // ── 雷达图 ──
    buildRadar (desc) {
      return {
        backgroundColor: C.bg,
        radar: {
          indicator: desc.indicators || [],
          shape: 'polygon',
          splitNumber: 4,
          axisName: { color: C.text, fontSize: 11 },
          splitLine: { lineStyle: { color: C.grid } },
          splitArea: { areaStyle: { color: [C.cardBg, C.bg] } },
          axisLine: { lineStyle: { color: C.border } }
        },
        series: [{
          type: 'radar',
          data: [{
            value: desc.values || [],
            areaStyle: { color: 'rgba(56, 189, 248, 0.15)' },
            lineStyle: { color: C.cyan, width: 2 },
            itemStyle: { color: C.cyan }
          }]
        }]
      }
    }
  },
  beforeDestroy () {
    this.disposeChart()
  }
}
</script>

<style>
.chart-dialog {
  background: #0C0F14 !important;
  border: 1px solid #334155;
  border-radius: 12px;
}
.chart-dialog .el-dialog__header {
  background: #0C0F14;
  border-bottom: 1px solid #1F2937;
  padding: 16px 20px;
}
.chart-dialog .el-dialog__title {
  color: #E2E8F0 !important;
  font-size: 15px;
  font-weight: 600;
}
.chart-dialog .el-dialog__headerbtn .el-dialog__close {
  color: #94A3B8;
}
.chart-dialog .el-dialog__body {
  background: #0C0F14;
  padding: 12px 16px 20px;
}
.chart-container {
  width: 100%;
  height: 450px;
}
</style>
