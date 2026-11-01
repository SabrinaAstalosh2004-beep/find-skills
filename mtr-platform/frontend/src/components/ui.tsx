import { useState, type ReactNode } from 'react'
import { api, fmt, money } from '../lib'
import { useApi, useApp } from '../state'
import { Chart } from './Chart'
import { DataTable, type TableSpec } from './DataTable'

export function Spinner({ label = 'Расчёт…' }: { label?: string }) {
  return <div className="flex items-center gap-2 p-6 text-sm text-slate-500"><span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-blue-600" />{label}</div>
}
export function ErrorBox({ msg }: { msg: string }) {
  return <div className="card border-red-200 bg-red-50 p-4 text-sm text-red-700">Ошибка: {msg}</div>
}

export function DemoBanner() {
  const { meta } = useApp()
  if (!meta?.meta?.is_demo) return null
  return (
    <div className="flex items-center justify-center gap-2 bg-amber-400 px-3 py-1 text-[11px] font-bold uppercase tracking-wider text-amber-950">
      Демонстрационные данные · синтетический набор · не являются корпоративными показателями
    </div>
  )
}

export function KpiCard({ k }: { k: any }) {
  const good = k.delta == null || k.hib == null ? null : (k.hib ? k.delta >= 0 : k.delta <= 0)
  const st = k.state || k.status
  return (
    <div className={`card relative p-3 ${st === 'bad' ? 'border-l-4 border-l-red-500' : st === 'ok' ? 'border-l-4 border-l-emerald-500' : ''}`} title={k.note || ''}>
      <div className="text-[11px] font-medium leading-tight text-slate-500">{k.label}</div>
      <div className="mt-1 text-xl font-semibold tracking-tight text-slate-900 tabular-nums">{fmt(k.value, k.unit)}</div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px]">
        {k.delta != null && (
          <span className={good == null ? 'text-slate-500' : good ? 'text-emerald-700' : 'text-red-600'}>
            {k.delta > 0 ? '▲' : k.delta < 0 ? '▼' : '■'} {fmt(Math.abs(k.delta), k.unit === 'days' ? 'days' : k.unit === 'pct' ? 'pct' : k.unit)}{k.delta_pct != null && k.unit === 'rub' ? ` (${k.delta_pct > 0 ? '+' : ''}${k.delta_pct.toFixed(1).replace('.', ',')}%)` : ''} к сравн.
          </span>
        )}
        {k.target != null && <span className="text-slate-500">цель {fmt(k.target, k.unit)}</span>}
      </div>
      {k.sub && <div className="mt-1 text-[11px] leading-snug text-slate-500">{k.sub}</div>}
      {k.note && <div className="absolute right-2 top-2 cursor-help text-[10px] text-slate-400" title={k.note}>ⓘ</div>}
    </div>
  )
}

function labelToValue(meta: any, dim: string, label: string): string | null {
  const opts = meta?.options?.[dim]
  if (!opts) return label
  const clean = (s: string) => s.replace(/^— /, '').trim()
  const o = opts.find((x: any) => clean(x.label) === label || x.value === label || clean(x.label).startsWith(label))
  return o ? o.value : null
}

export function Section({ s, onControl }: { s: any; onControl: (key: string, value: string) => void }) {
  const { meta, setDrill } = useApp()
  const [mode, setMode] = useState<'chart' | 'table'>(s.chart ? 'chart' : 'table')
  const drillDim = s.drill?.dim || s.table?.drill?.dim
  const onChartClick = (p: any) => {
    if (p?.data?.position_id) return setDrill({ positionId: p.data.position_id })
    if (!drillDim) return
    let label = p.name
    if (s.chart?.kind === 'heatmap') {
      if (s.drill?.keys) return setDrill({ dim: drillDim, value: s.drill.keys[p.value[1]], label: s.chart.y[p.value[1]] })
      label = s.chart.y[p.value[1]]
    }
    const v = labelToValue(meta, drillDim, label)
    if (v) setDrill({ dim: drillDim, value: v, label })
  }
  const onRow = (r: any) => {
    if (s.table?.row_key === 'position_id' && r.position_id) return setDrill({ positionId: r.position_id })
    const d = s.table?.drill
    if (d?.dim && d.key && r[d.key] !== undefined) {
      const lblKey = Object.keys(r).find(k => k.endsWith('_label'))
      setDrill({ dim: d.dim, value: r[d.key], label: lblKey ? r[lblKey] : r[d.key] })
    }
  }
  const { f, bump } = useApp()
  const onDecision = s.kind === 'redistribution' ? async (row: any, decision: string) => {
    await api('/redistribution/decision', f, { method: 'POST', body: { key: row.decision_key, decision, row } })
    bump()
  } : undefined
  return (
    <div className={`card flex flex-col p-3 ${s.span === 2 ? 'xl:col-span-2' : ''}`}>
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-[13px] font-semibold leading-snug text-slate-900">{s.title}</h3>
          {s.subtitle && <p className="mt-0.5 text-[11px] leading-snug text-slate-500">{s.subtitle}</p>}
        </div>
        <div className="no-print flex flex-wrap items-center gap-1.5">
          {s.controls?.map((c: any) => (
            <label key={c.key} className="flex items-center gap-1 text-[11px] text-slate-500">{c.label}
              <select className="sel max-w-[220px]" value={c.value} onChange={e => onControl(c.key, e.target.value)}>
                {c.options.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
          ))}
          {s.chart && s.table && (
            <div className="flex overflow-hidden rounded-md border border-slate-300 text-[11px]">
              <button className={`px-2 py-1 ${mode === 'chart' ? 'bg-slate-800 text-white' : 'bg-white'}`} onClick={() => setMode('chart')}>График</button>
              <button className={`px-2 py-1 ${mode === 'table' ? 'bg-slate-800 text-white' : 'bg-white'}`} onClick={() => setMode('table')}>Таблица</button>
            </div>
          )}
        </div>
      </div>
      {s.kind === 'hierarchy' ? <Hierarchy levels={s.levels} /> : (
        <>
          {s.chart && mode === 'chart' && <Chart spec={s.chart} onClick={onChartClick} />}
          {s.table && (mode === 'table' || !s.chart) && (s.table.rows.length ? <DataTable spec={s.table} onRow={(s.table.drill || s.table.row_key === 'position_id') ? onRow : undefined} onDecision={onDecision} /> : <div className="p-3 text-xs text-slate-500">Нет строк для выбранного среза.</div>)}
          {!s.chart && !s.table && !s.note && <div className="p-3 text-xs text-slate-500">Нет данных для выбранного среза.</div>}
        </>
      )}
      {s.note && <p className="mt-2 border-t border-slate-100 pt-2 text-[11px] leading-snug text-slate-500">ⓘ {s.note}</p>}
      {(drillDim || s.chart?.kind === 'scatter') && s.kind !== 'hierarchy' && <p className="no-print mt-1 text-[10px] text-slate-400">Нажмите на элемент графика или строку таблицы для детализации до номенклатуры</p>}
    </div>
  )
}

const LEVEL_LABEL: Record<string, string> = { dgroup: 'Группа', direction: 'Направление', company: 'Общество', service: 'Служба', mclass: 'Класс МТР', material: 'Номенклатура' }

function Hierarchy({ levels }: { levels: string[] }) {
  const [path, setPath] = useState<{ dim: string; value: string; label: string }[]>([])
  const level = levels[Math.min(path.length, levels.length - 1)]
  const { data, loading, err } = useApi<TableSpec>('/hierarchy', { level, path: path.map(p => `${p.dim}:${p.value}`).join('|') })
  const { setDrill } = useApp()
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-1 text-[11px]">
        <button className="btn" onClick={() => setPath([])}>Группа (всё)</button>
        {path.map((p, i) => <span key={i} className="flex items-center gap-1">→ <button className="btn" onClick={() => setPath(path.slice(0, i + 1))}>{LEVEL_LABEL[p.dim]}: {p.label}</button></span>)}
        <span className="text-slate-400">→ уровень: {LEVEL_LABEL[level]}</span>
      </div>
      {loading && <Spinner />}{err && <ErrorBox msg={err} />}
      {data && <DataTable spec={data} onRow={r => {
        const lbl = r[`${level}_label`]
        if (path.length >= levels.length - 1) setDrill({ dim: level, value: r[level], label: lbl })
        else setPath([...path, { dim: level, value: r[level], label: lbl }])
      }} />}
    </div>
  )
}

export function InsightCard({ i, onAccept, compact }: { i: any; onAccept?: (i: any) => void; compact?: boolean }) {
  const [open, setOpen] = useState(false)
  const kc: Record<string, string> = { 'Аномалия': 'bg-red-50 text-red-700', 'Закономерность': 'bg-violet-50 text-violet-700' }
  const cs: Record<string, string> = { 'Подтверждено данными': 'text-emerald-700', 'Зависимость (не доказанная причина)': 'text-amber-700', 'Гипотеза, требует проверки': 'text-slate-500' }
  return (
    <div className="rounded-md border border-slate-200 bg-white p-2.5 text-xs">
      <div className="flex items-start justify-between gap-2">
        <span className={`chip ${kc[i.kind] || 'bg-slate-100 text-slate-600'}`}>{i.kind}</span>
        <span className="font-semibold tabular-nums text-slate-800">{money(i.value_at_risk)}</span>
      </div>
      <div className="mt-1 font-medium leading-snug text-slate-900">{i.title}</div>
      {!compact && <div className="mt-1 leading-snug text-slate-600">{i.observation}</div>}
      <div className="mt-1 leading-snug"><span className="text-slate-500">Причина: </span>{i.cause} <span className={`font-medium ${cs[i.cause_status] || ''}`}>[{i.cause_status}]</span></div>
      <button className="mt-1 text-[11px] text-blue-700 hover:underline" onClick={() => setOpen(!open)}>{open ? 'Свернуть' : 'Доказательства, проверки, действие'}</button>
      {open && (
        <div className="mt-1 space-y-1.5 border-t border-slate-100 pt-1.5">
          <div><div className="font-semibold text-slate-600">Количественное подтверждение</div>
            <ul className="ml-3 list-disc">{i.evidence.map((e: any, k: number) => <li key={k}>{e.label}: <b>{fmt(e.value, e.unit)}</b></li>)}</ul></div>
          <div><div className="font-semibold text-slate-600">Необходимые проверки</div><ul className="ml-3 list-disc">{i.checks.map((c: string, k: number) => <li key={k}>{c}</li>)}</ul></div>
          <div><span className="font-semibold text-slate-600">Рекомендуемое действие: </span>{i.action}</div>
          <div><span className="font-semibold text-slate-600">Ожидаемый результат: </span>{i.effect != null ? money(i.effect) + ' — ' : ''}{i.effect_note}</div>
          <div><span className="font-semibold text-slate-600">Ответственный: </span>{i.owner}{i.decision_needed && <span className="chip ml-1 bg-red-100 text-red-700">нужно решение</span>}</div>
          {i.method && <div className="text-slate-500">Метод: {i.method}</div>}
        </div>
      )}
      {onAccept && <button className="btn mt-2 w-full justify-center" onClick={() => onAccept(i)}>Принять в работу → реестр мероприятий</button>}
    </div>
  )
}

export function InsightsPanel({ items }: { items: any[] }) {
  const { f, bump } = useApp()
  const [msg, setMsg] = useState<string | null>(null)
  const accept = async (i: any) => {
    try { const r = await api('/actions', f, { method: 'POST', body: { insight_id: i.id } }); setMsg(`Создано мероприятие ${r.action_id} (ответственный: ${r.owner})`); bump() }
    catch (e: any) { setMsg(e.message) }
  }
  return (
    <div className="space-y-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Отклонения, риски и рекомендации</div>
      {msg && <div className="rounded bg-emerald-50 p-2 text-[11px] text-emerald-800">{msg}</div>}
      {items.length === 0 && <div className="text-xs text-slate-500">Существенных отклонений для этой витрины не выявлено.</div>}
      {items.map(i => <InsightCard key={i.id} i={i} onAccept={accept} compact />)}
    </div>
  )
}

export function Modal({ title, onClose, children, wide }: { title: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-2 sm:p-6" onClick={onClose}>
      <div className={`card w-full ${wide ? 'max-w-7xl' : 'max-w-3xl'} p-4`} onClick={e => e.stopPropagation()}>
        <div className="mb-3 flex items-start justify-between gap-2"><div className="text-sm font-semibold text-slate-900">{title}</div><button className="btn" onClick={onClose}>Закрыть ✕</button></div>
        {children}
      </div>
    </div>
  )
}

export function DrillModal() {
  const { drill, setDrill, setFilter, meta } = useApp()
  if (!drill) return null
  if (drill.positionId) return <PositionModal id={drill.positionId} onClose={() => setDrill(null)} />
  return <NomenclatureModal />
}

function NomenclatureModal() {
  const { drill, setDrill, setFilter, meta } = useApp()
  const { data, loading, err } = useApi<any>('/drill', drill?.dim ? { dim: drill.dim, value: drill.value } : {})
  const dimLabel = meta?.dimensions?.find((d: any) => d.key === drill?.dim)?.label
  return (
    <Modal wide title={<>Детализация до номенклатуры{drill?.dim ? <> · {dimLabel}: <span className="text-blue-700">{drill.label}</span></> : ' · текущий срез'}</>} onClose={() => setDrill(null)}>
      {drill?.dim && <button className="btn-primary mb-3" onClick={() => { setFilter(drill.dim!, [drill.value!]); setDrill(null) }}>Применить «{drill.label}» как сквозной фильтр для всех витрин</button>}
      {loading && <Spinner />}{err && <ErrorBox msg={err} />}
      {data && <DataTable spec={data.table} pageSize={20} compact onRow={r => setDrill({ positionId: r.position_id })} />}
    </Modal>
  )
}

function PositionModal({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, loading, err } = useApi<any>(`/position/${id}`)
  return (
    <Modal wide title={data ? `${data.info.material_name} · ${data.info.nsi_code} · ${data.info.company_name}` : 'Позиция'} onClose={onClose}>
      {loading && <Spinner />}{err && <ErrorBox msg={err} />}
      {data && (
        <div className="space-y-3 text-xs">
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 md:grid-cols-4">
            {[['Склад', data.info.warehouse_name], ['Направление', data.info.direction_name], ['Программа', data.info.program], ['Служба', data.info.service_name],
              ['Класс / группа', `${data.info.mclass} / ${data.info.mgroup}`], ['Критичность', data.info.criticality], ['Политика пополнения', data.info.replenishment_policy],
              ['Тип спроса', data.info.demand_type], ['Проект', data.info.project_name || '—'], ['Статус проекта', data.info.project_status || '—'],
              ['Производитель / модель', `${data.info.manufacturer} / ${data.info.model}`], ['Срок поставки', `${data.info.lead_days} дн.`],
              ['Аналоги', data.info.analog_group ? `${data.info.analog_group} (${data.info.analog_status})` : 'нет'], ['Собственность', data.info.balance_ownership]].map(([a, b]) =>
              <div key={a as string}><span className="text-slate-500">{a}: </span><span className="font-medium">{b as string}</span></div>)}
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            <div className="card p-2"><div className="mb-1 font-semibold">Остаток, свободный запас и НЭЗ на конец месяца</div>
              <Chart height={220} spec={{ kind: 'line', unit: 'rub', x: data.snapshots.map((s: any) => s.label), series: [
                { name: 'Остаток', data: data.snapshots.map((s: any) => s.value), area: true }, { name: 'Свободно', data: data.snapshots.map((s: any) => s.free_value) },
                { name: 'НЭЗ', data: data.snapshots.map((s: any) => s.nez_value), color: 'bad' }] }} /></div>
            <div className="card p-2"><div className="mb-1 font-semibold">Плановая потребность (кол-во): первоначальная и оперативная</div>
              <Chart height={220} spec={{ kind: 'bar', unit: 'num', categories: data.demand.map((d: any) => d.label), series: [
                { name: 'Оперативный план', data: data.demand.map((d: any) => d.plan_qty) }, { name: 'Первоначальный план', data: data.demand.map((d: any) => d.plan_init_qty), muted: true }] }} /></div>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            <div><div className="mb-1 font-semibold">Движения (последние)</div>
              <DataTable compact pageSize={10} spec={{ columns: [{ key: 'date', label: 'Дата', type: 'date' }, { key: 'mtype', label: 'Операция', type: 'text' }, { key: 'subtype', label: 'Вид', type: 'text' },
                { key: 'qty', label: 'Кол-во', type: 'num' }, { key: 'value', label: 'Стоимость', type: 'money' }, { key: 'po_id', label: 'Заказ', type: 'text' }], rows: data.movements }} /></div>
            <div><div className="mb-1 font-semibold">Заказы поставщикам</div>
              <DataTable compact pageSize={10} spec={{ columns: [{ key: 'po_id', label: 'Заказ', type: 'text' }, { key: 'order_date', label: 'Дата', type: 'date' }, { key: 'qty', label: 'Кол-во', type: 'num' },
                { key: 'value', label: 'Стоимость', type: 'money' }, { key: 'planned_delivery', label: 'План. поставка', type: 'date' }, { key: 'actual_delivery', label: 'Факт/ожид.', type: 'date' },
                { key: 'need_date', label: 'Потребность', type: 'date' }, { key: 'proc_model', label: 'Модель', type: 'text' }], rows: data.purchase_orders }} /></div>
          </div>
        </div>
      )}
    </Modal>
  )
}
