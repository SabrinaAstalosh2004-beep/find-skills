import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import { fmt, moneyShort, nf } from '../lib'

// Единая фабрика графиков ECharts. Сервер передаёт данные и тип, оформление — здесь.
export const PALETTE = ['#2563eb', '#f59e0b', '#0d9488', '#7c3aed', '#0891b2', '#db2777', '#65a30d', '#ea580c', '#475569', '#9333ea', '#0ea5e9', '#a16207']
const BAD = '#dc2626', GOOD = '#16a34a', MUTED = '#cbd5e1', AXIS = '#94a3b8', GRID = '#eef2f7'

const axisFmt = (unit: string) => (v: number) => unit === 'rub' ? moneyShort(v) : unit === 'pct' ? `${nf(v, 0)}%` : unit === 'days' ? `${nf(v, 0)}` : nf(v, Math.abs(v) < 10 && v !== 0 ? 1 : 0)
const tipFmt = (unit: string) => (v: any) => fmt(typeof v === 'object' && v !== null ? v.value : v, unit)
const base = (unit: string) => ({
  textStyle: { fontFamily: 'Inter, Segoe UI, Roboto, Arial, sans-serif', color: '#334155' },
  grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
  legend: { top: 0, left: 0, type: 'scroll', textStyle: { fontSize: 11, color: '#475569' }, itemWidth: 12, itemHeight: 8 },
  tooltip: { trigger: 'axis', valueFormatter: tipFmt(unit), confine: true, textStyle: { fontSize: 12 } },
  animationDuration: 250,
})
const valAxis = (unit: string, extra: any = {}) => ({
  type: 'value', axisLabel: { formatter: axisFmt(unit), color: AXIS, fontSize: 10 }, splitLine: { lineStyle: { color: GRID } }, ...extra,
})
const catAxis = (data: string[], extra: any = {}) => ({
  type: 'category', data, axisLabel: { color: '#64748b', fontSize: 10, hideOverlap: true, width: 140, overflow: 'truncate' },
  axisLine: { lineStyle: { color: '#cbd5e1' } }, axisTick: { show: false }, ...extra,
})
const colorOf = (s: any, i: number) => s.color === 'bad' ? BAD : s.color === 'good' ? GOOD : s.muted ? MUTED : PALETTE[i % PALETTE.length]

function build(spec: any): any {
  const u = spec.unit || 'num'
  switch (spec.kind) {
    case 'line': {
      const hasY2 = spec.series.some((s: any) => s.y2)
      return {
        ...base(u),
        xAxis: catAxis(spec.x, { boundaryGap: spec.series.some((s: any) => s.type === 'bar') }),
        yAxis: hasY2 ? [valAxis(u), valAxis('pct', { splitLine: { show: false } })] : valAxis(u, { scale: u === 'days' || u === 'index' }),
        series: spec.series.map((s: any, i: number) => ({
          name: s.name, type: s.type || 'line', data: s.data, smooth: false, showSymbol: false, yAxisIndex: s.y2 ? 1 : 0,
          lineStyle: { width: s.muted ? 1 : 2, type: s.dashed ? 'dashed' : 'solid' }, itemStyle: { color: colorOf(s, i) },
          areaStyle: s.area ? { opacity: 0.08 } : undefined, barMaxWidth: 14,
          markLine: i === 0 && spec.mark_line ? { symbol: 'none', data: [{ yAxis: spec.mark_line.value, label: { formatter: spec.mark_line.label, fontSize: 10 } }], lineStyle: { color: BAD, type: 'dashed' } } : undefined,
        })),
      }
    }
    case 'band': {
      const lo = spec.lower, hi = spec.upper
      return {
        ...base(u),
        legend: { ...base(u).legend, data: [spec.band_label, ...spec.series.map((s: any) => s.name)] },
        xAxis: catAxis(spec.x, { boundaryGap: true }),
        yAxis: valAxis(u, { scale: true }),
        series: [
          { name: 'P10', type: 'line', data: lo, stack: 'band', lineStyle: { opacity: 0 }, showSymbol: false, tooltip: { show: true } },
          { name: spec.band_label, type: 'line', data: hi.map((h: number, i: number) => h - lo[i]), stack: 'band', lineStyle: { opacity: 0 }, areaStyle: { color: '#93c5fd', opacity: 0.35 }, showSymbol: false },
          ...spec.series.map((s: any, i: number) => ({ name: s.name, type: s.type || 'line', data: s.data, itemStyle: { color: s.muted ? MUTED : PALETTE[i] }, lineStyle: { width: 2, type: s.dashed ? 'dashed' : 'solid' }, barMaxWidth: 18 })),
        ],
      }
    }
    case 'bar': {
      const hz = spec.horizontal
      const cats = spec.categories
      const series = spec.series.map((s: any, i: number) => {
        const isLine = s.type === 'line'
        return {
          name: s.name, type: isLine ? 'line' : 'bar', data: s.data.map((v: number, j: number) => {
            if (s.signed) {
              const bad = s.invert ? v < 0 : v > 0
              return { value: v, itemStyle: { color: s.highlight && s.highlight[j] ? '#f59e0b' : bad ? BAD : GOOD } }
            }
            if (s.highlight && s.highlight[j]) return { value: v, itemStyle: { color: '#f59e0b' } }
            return v
          }),
          stack: spec.stacked && !isLine ? 'a' : undefined, itemStyle: { color: colorOf(s, i) }, barMaxWidth: 26, yAxisIndex: s.y2 ? 1 : 0,
          showSymbol: false, lineStyle: { width: 2 },
          markLine: i === 0 && spec.mark_line ? { symbol: 'none', data: [hz ? { xAxis: spec.mark_line.value } : { yAxis: spec.mark_line.value }], label: { formatter: spec.mark_line.label, fontSize: 10 }, lineStyle: { color: BAD, type: 'dashed' } } : undefined,
        }
      })
      const hasY2 = spec.series.some((s: any) => s.y2)
      const height = hz ? Math.max(260, cats.length * 22 + 60) : undefined
      return {
        ...base(u), _height: height,
        tooltip: { ...base(u).tooltip, axisPointer: { type: 'shadow' } },
        xAxis: hz ? valAxis(u) : catAxis(cats, cats.length <= 8 ? { axisLabel: { interval: 0, color: '#64748b', fontSize: 10, width: 120, overflow: 'truncate' } } : {}),
        yAxis: hz ? catAxis(cats, { inverse: false }) : (hasY2 ? [valAxis(u), valAxis('pct', { splitLine: { show: false } })] : valAxis(u)),
        series,
      }
    }
    case 'waterfall': {
      const items = spec.items
      const names = items.map((i: any) => i.name)
      const baseArr: any[] = [], pos: any[] = [], neg: any[] = [], tot: any[] = []
      let run = 0
      items.forEach((it: any) => {
        if (it.type === 'total') { run = it.value; baseArr.push(0); tot.push(it.value); pos.push('-'); neg.push('-') }
        else {
          const v = it.value || 0
          const start = run, end = run + v
          baseArr.push(Math.min(start, end)); tot.push('-')
          if (v >= 0) { pos.push(v); neg.push('-') } else { neg.push(-v); pos.push('-') }
          run = end
        }
      })
      // если изменения малы относительно итогов — ось начинается не с нуля, чтобы факторы были различимы
      const levels: number[] = []
      let r2 = 0
      items.forEach((it: any) => { if (it.type === 'total') { r2 = it.value } else { levels.push(r2); r2 += it.value || 0 } levels.push(r2) })
      const maxDelta = Math.max(0, ...items.filter((i: any) => i.type !== 'total').map((i: any) => Math.abs(i.value || 0)))
      const maxTot = Math.max(0, ...items.filter((i: any) => i.type === 'total').map((i: any) => Math.abs(i.value || 0)))
      const minLvl = Math.min(...levels)
      let yMin: number | undefined = undefined
      if (u !== 'days' && maxTot > 0 && maxDelta < 0.2 * maxTot && minLvl > 0) {
        const pad = Math.max(maxDelta * 1.5, maxTot * 0.02)
        const mag = Math.pow(10, Math.floor(Math.log10(Math.max(1, minLvl - pad))))
        yMin = Math.max(0, Math.floor((minLvl - pad) / mag) * mag)
      }
      return {
        ...base(u), legend: { show: false },
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, confine: true, formatter: (ps: any) => { const i = ps[0].dataIndex; return `${names[i]}<br/><b>${fmt(items[i].value, u)}</b>` } },
        xAxis: catAxis(names, { axisLabel: { interval: 0, rotate: names.length > 5 ? 30 : 0, fontSize: 10, color: '#64748b', width: 96, overflow: 'truncate' } }),
        yAxis: valAxis(u, { scale: true, min: yMin }),
        series: [
          { type: 'bar', stack: 'w', data: baseArr, itemStyle: { color: 'transparent' }, emphasis: { disabled: true }, silent: true },
          { name: 'Итог', type: 'bar', stack: 'w', data: tot, itemStyle: { color: '#334155' }, barMaxWidth: 44, label: { show: true, position: 'top', formatter: (p: any) => fmt(p.value, u, true), fontSize: 10 } },
          { name: 'Увеличение', type: 'bar', stack: 'w', data: pos, itemStyle: { color: u === 'days' ? BAD : '#f59e0b' }, barMaxWidth: 44, label: { show: true, position: 'top', formatter: (p: any) => '+' + fmt(p.value, u, true), fontSize: 10 } },
          { name: 'Уменьшение', type: 'bar', stack: 'w', data: neg, itemStyle: { color: u === 'days' ? GOOD : '#0d9488' }, barMaxWidth: 44, label: { show: true, position: 'bottom', formatter: (p: any) => '−' + fmt(p.value, u, true), fontSize: 10 } },
        ],
      }
    }
    case 'heatmap': {
      const data: any[] = []
      let mn = Infinity, mx = -Infinity
      spec.values.forEach((row: any[], yi: number) => row.forEach((v: any, xi: number) => {
        if (v !== null && v !== undefined) { mn = Math.min(mn, v); mx = Math.max(mx, v) }
        data.push([xi, yi, v ?? '-'])
      }))
      const lim = Math.max(Math.abs(mn), Math.abs(mx)) || 1
      return {
        textStyle: base(u).textStyle, _height: Math.max(240, spec.y.length * 26 + 90),
        tooltip: { confine: true, formatter: (p: any) => `${spec.y[p.value[1]]} · ${spec.x[p.value[0]]}<br/><b>${spec.labels ? spec.labels[p.value[1]][p.value[0]] : fmt(p.value[2], u)}</b>` },
        grid: { left: 8, right: 16, top: 8, bottom: 56, containLabel: true },
        xAxis: { type: 'category', data: spec.x, axisLabel: { rotate: spec.x.length > 6 ? 30 : 0, fontSize: 10, color: '#64748b', interval: 0, width: 120, overflow: 'truncate' }, splitArea: { show: false } },
        yAxis: { type: 'category', data: spec.y, axisLabel: { fontSize: 10, color: '#475569', width: 170, overflow: 'truncate' }, inverse: true },
        visualMap: spec.diverging
          ? { min: -lim, max: lim, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemHeight: 120, itemWidth: 10, inRange: { color: ['#0d9488', '#f8fafc', '#dc2626'] }, text: ['хуже', 'лучше'], textStyle: { fontSize: 10 }, show: u !== 'score' || true }
          : { min: Math.min(0, mn), max: mx || 1, orient: 'horizontal', left: 'center', bottom: 0, itemHeight: 120, itemWidth: 10, inRange: { color: ['#f1f5f9', '#93c5fd', '#1d4ed8'] }, textStyle: { fontSize: 10 }, formatter: (v: number) => fmt(v, u, true) },
        series: [{ type: 'heatmap', data, label: { show: spec.x.length * spec.y.length <= 120, fontSize: 9, color: '#0f172a', formatter: (p: any) => spec.labels ? spec.labels[p.value[1]][p.value[0]] : fmt(p.value[2], u, true) }, itemStyle: { borderColor: '#fff', borderWidth: 1 } }],
      }
    }
    case 'treemap':
      return {
        textStyle: base(u).textStyle, _height: 380,
        tooltip: { confine: true, formatter: (p: any) => `${p.treePathInfo?.map((x: any) => x.name).filter(Boolean).join(' → ')}<br/><b>${fmt(p.value, u)}</b>${p.data?.turnover ? `<br/>Оборачиваемость: ${nf(p.data.turnover, 0)} дн.` : ''}` },
        series: [{ type: 'treemap', data: spec.nodes, roam: false, nodeClick: 'zoomToNode', breadcrumb: { show: true, bottom: 0, itemStyle: { color: '#e2e8f0', textStyle: { color: '#334155' } } },
          label: { fontSize: 11, formatter: (p: any) => `${p.name}\n${fmt(p.value, u, true)}` }, upperLabel: { show: true, height: 18, fontSize: 10, color: '#fff' },
          levels: [{ itemStyle: { borderColor: '#fff', borderWidth: 2, gapWidth: 2 } }, { colorSaturation: [0.35, 0.6], itemStyle: { borderColorSaturation: 0.7, gapWidth: 1, borderWidth: 1 } }],
          color: PALETTE, top: 4, left: 2, right: 2, bottom: 26 }],
      }
    case 'sankey':
      return {
        textStyle: base(u).textStyle, _height: Math.max(320, spec.nodes.length * 26),
        tooltip: { trigger: 'item', confine: true, valueFormatter: tipFmt(u) },
        series: [{ type: 'sankey', data: spec.nodes, links: spec.links, emphasis: { focus: 'adjacency' }, nodeGap: 10, label: { fontSize: 10 }, lineStyle: { color: 'gradient', opacity: 0.35 }, left: 4, right: 140 }],
      }
    case 'pareto': {
      const th = spec.thresholds || {}
      return {
        ...base(u),
        xAxis: catAxis(spec.categories, { axisLabel: { rotate: 35, fontSize: 9, color: '#64748b', interval: spec.categories.length > 25 ? 'auto' : 0, width: 100, overflow: 'truncate' } }),
        yAxis: [valAxis(u), { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: AXIS, fontSize: 10 }, splitLine: { show: false } }],
        tooltip: { trigger: 'axis', confine: true, formatter: (ps: any) => `${ps[0].name}<br/>${fmt(ps[0].value, u)}<br/>Накопленно: ${nf(ps[1]?.value ?? 0, 1)}%` },
        series: [
          { name: 'Значение', type: 'bar', data: spec.values, itemStyle: { color: '#2563eb' }, barMaxWidth: 22 },
          { name: 'Накопленная доля', type: 'line', yAxisIndex: 1, data: spec.cum_share, itemStyle: { color: '#f59e0b' }, showSymbol: false,
            markLine: { symbol: 'none', lineStyle: { type: 'dashed', color: '#94a3b8' }, label: { fontSize: 9 }, data: [{ yAxis: 50, label: { formatter: `50% · ${th['50'] ?? ''}` } }, { yAxis: 80, label: { formatter: `80% · ${th['80'] ?? ''}` } }, { yAxis: 90, label: { formatter: `90% · ${th['90'] ?? ''}` } }] } },
        ],
      }
    }
    case 'scatter': {
      const groups: string[] = spec.groups || Array.from(new Set(spec.points.map((p: any) => p.group)))
      const maxS = Math.max(1, ...spec.points.map((p: any) => Math.abs(p.size || 1)))
      const xu = spec.x_unit, yu = spec.y_unit
      const ml: any[] = []
      if (spec.vline !== undefined) ml.push({ xAxis: spec.vline })
      if (spec.hline !== undefined) ml.push({ yAxis: spec.hline })
      return {
        ...base(yu),
        tooltip: { trigger: 'item', confine: true, formatter: (p: any) => `<b>${p.data.name}</b><br/>${spec.x_label}: ${fmt(p.data.value[0], xu)}<br/>${spec.y_label}: ${fmt(p.data.value[1], yu)}${spec.size_label ? `<br/>${spec.size_label}: ${fmt(p.data.size, 'rub')}` : ''}<br/>${p.seriesName}` },
        grid: { left: 8, right: 20, top: 58, bottom: 24, containLabel: true },
        xAxis: { ...valAxis(xu), name: spec.x_label, nameLocation: 'middle', nameGap: 22, nameTextStyle: { fontSize: 10, color: '#64748b' }, type: spec.xlog ? 'log' : 'value', scale: true },
        yAxis: { ...valAxis(yu), name: spec.y_label, nameTextStyle: { fontSize: 10, color: '#64748b', align: 'left' }, type: spec.ylog ? 'log' : 'value', scale: !spec.ylog },
        series: groups.map((g, i) => ({
          name: g, type: 'scatter', itemStyle: { color: g.startsWith('A') ? BAD : PALETTE[i % PALETTE.length], opacity: 0.75, borderColor: '#fff', borderWidth: 0.5 },
          symbolSize: (_: any, p: any) => 6 + 30 * Math.sqrt(Math.abs(p.data.size || 1) / maxS),
          data: spec.points.filter((p: any) => p.group === g && p.x !== null && p.y !== null && (!spec.ylog || p.y > 0)).map((p: any) => ({ name: p.name, value: [p.x, p.y], size: p.size, position_id: p.position_id, symbol: p.symbol })),
          symbol: (_: any, p: any) => p.data.symbol || 'circle',
          markLine: i === 0 && ml.length ? { symbol: 'none', silent: true, lineStyle: { type: 'dashed', color: '#94a3b8' }, data: ml, label: { show: false } } : undefined,
        })),
      }
    }
    case 'gantt': {
      const items = spec.items
      const labels = spec.labels
      const names = items.map((i: any) => i.name)
      const statusColor: Record<string, string> = { 'В графике': '#2563eb', 'Перенесён': '#f59e0b', 'Отменён': BAD, 'Завершён': '#94a3b8', 'Изменено техническое решение': '#7c3aed' }
      return {
        textStyle: base(u).textStyle, _height: Math.max(220, items.length * 24 + 70),
        tooltip: { confine: true, formatter: (p: any) => { const it = items[p.value[0]]; return `<b>${it.name}</b><br/>Статус: ${it.status}<br/>Начало: ${labels[it.start] ?? it.start}<br/>План. окончание: ${labels[it.end] ?? it.end}<br/>Актуальное окончание: ${labels[it.rev_end] ?? it.rev_end}${it.progress != null ? `<br/>Прогресс: ${nf(it.progress, 0)}%` : ''}` } },
        grid: { left: 8, right: 16, top: 24, bottom: 24, containLabel: true },
        xAxis: { type: 'value', min: Math.min(...items.map((i: any) => i.start)) - 1, max: Math.max(...items.map((i: any) => i.rev_end)) + 1, axisLabel: { formatter: (v: number) => labels[Math.round(v)] ?? '', fontSize: 10, color: AXIS }, splitLine: { lineStyle: { color: GRID } } },
        yAxis: { type: 'category', data: names, inverse: true, axisLabel: { fontSize: 10, width: 220, overflow: 'truncate', color: '#475569' } },
        series: [{
          type: 'custom', encode: { x: [1, 2], y: 0 },
          renderItem: (params: any, api: any) => {
            const i = api.value(0), it = items[i]
            const y = api.coord([0, i])[1]
            const h = api.size([0, 1])[1] * 0.55
            const s = api.coord([it.start, i])[0], e = api.coord([it.end, i])[0], re = api.coord([it.rev_end, i])[0]
            const col = statusColor[it.status] || '#2563eb'
            const children: any[] = [{ type: 'rect', shape: { x: s, y: y - h / 2, width: Math.max(2, e - s), height: h }, style: { fill: col, opacity: 0.85 } }]
            if (re > e) children.push({ type: 'rect', shape: { x: e, y: y - h / 2, width: re - e, height: h }, style: { fill: 'none', stroke: col, lineDash: [4, 3] } })
            if (it.event != null) { const ex = api.coord([it.event, i])[0]; children.push({ type: 'path', shape: { pathData: `M${ex},${y - h} L${ex + 5},${y} L${ex},${y + h} L${ex - 5},${y} Z` }, style: { fill: '#0f172a' } }) }
            return { type: 'group', children }
          },
          data: items.map((it: any, i: number) => [i, it.start, it.rev_end]),
          markLine: { symbol: 'none', silent: true, data: [{ xAxis: spec.now_m }], lineStyle: { color: BAD, type: 'solid' }, label: { formatter: `Срез: ${spec.now}`, fontSize: 10 } },
        }],
      }
    }
  }
  return {}
}

export function Chart({ spec, onClick, height }: { spec: any; onClick?: (p: any) => void; height?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const inst = useRef<echarts.ECharts | null>(null)
  const opt = spec ? build(spec) : null
  const h = height || opt?._height || 300
  useEffect(() => {
    if (!ref.current || !opt) return
    if (!inst.current) inst.current = echarts.init(ref.current, undefined, { renderer: 'canvas' })
    const { _height, ...o } = opt
    inst.current.setOption({ color: PALETTE, ...o }, true)
    inst.current.off('click')
    if (onClick) inst.current.on('click', onClick)
    const ro = new ResizeObserver(() => inst.current?.resize())
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [JSON.stringify(spec), onClick])
  useEffect(() => () => { inst.current?.dispose(); inst.current = null }, [])
  if (!spec) return null
  return <div ref={ref} style={{ height: h, width: '100%' }} role="img" aria-label={spec.kind} />
}
