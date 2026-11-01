import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api, fmt, query } from '../lib'
import { useApi, useApp } from '../state'
import { DataTable } from './DataTable'
import { DemoBanner, ErrorBox, Spinner } from './ui'

const EXTRA_PAGES = [
  { id: 'slice', title: 'Конструктор срезов' },
  { id: 'method', title: 'Методика и каталог метрик' },
  { id: 'sources', title: 'Источники данных' },
]

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { meta, page, setPage } = useApp()
  if (!meta) return null
  const go = (p: string) => { setPage(p); onClose() }
  return (
    <aside className={`fixed inset-y-0 left-0 z-40 w-64 transform overflow-y-auto bg-slate-900 text-slate-300 transition-transform scroll-thin lg:static lg:translate-x-0 ${open ? 'translate-x-0' : '-translate-x-full'}`}>
      <div className="border-b border-slate-800 px-4 py-3">
        <div className="text-[13px] font-semibold text-white">Запасы МТР</div>
        <div className="text-[11px] text-slate-400">Executive Intelligence · аналитическая платформа</div>
      </div>
      <nav className="px-2 py-2 text-[12.5px]">
        {meta.groups.map((g: string) => (
          <div key={g} className="mb-2">
            <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">{g}</div>
            {meta.vitrines.filter((v: any) => v.group === g).map((v: any) => (
              <button key={v.id} onClick={() => go(`v${v.id}`)} title={v.description}
                className={`flex w-full items-start gap-2 rounded px-2 py-1.5 text-left leading-tight ${page === `v${v.id}` ? 'bg-blue-700 text-white' : 'hover:bg-slate-800 hover:text-white'}`}>
                <span className="w-5 shrink-0 text-right tabular-nums text-slate-500">{v.id}</span><span>{v.title}</span>
              </button>
            ))}
          </div>
        ))}
        <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Инструменты</div>
        {EXTRA_PAGES.map(p => (
          <button key={p.id} onClick={() => go(p.id)} className={`flex w-full rounded px-2 py-1.5 pl-9 text-left ${page === p.id ? 'bg-blue-700 text-white' : 'hover:bg-slate-800 hover:text-white'}`}>{p.title}</button>
        ))}
      </nav>
    </aside>
  )
}

function MultiSelect({ label, options, value, onChange }: { label: string; options: any[]; value: string[]; onChange: (v: string[]) => void }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  const sel = new Set(value)
  const shown = options.filter(o => o.label.toLowerCase().includes(q.toLowerCase()))
  const txt = value.length === 0 ? 'все' : value.length === 1 ? (options.find(o => o.value === value[0])?.label || value[0]).replace(/^— /, '') : `выбрано: ${value.length}`
  return (
    <div className="relative" ref={ref}>
      <button className={`sel flex max-w-[190px] items-center gap-1 ${value.length ? 'border-blue-500 bg-blue-50 text-blue-800' : ''}`} onClick={() => setOpen(!open)}>
        <span className="text-slate-500">{label}:</span><span className="truncate font-medium">{txt}</span><span className="text-slate-400">▾</span>
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-72 rounded-md border border-slate-200 bg-white p-2 shadow-lg">
          <input autoFocus className="sel mb-1 w-full" placeholder="Поиск…" value={q} onChange={e => setQ(e.target.value)} />
          <div className="max-h-64 overflow-y-auto scroll-thin">
            {shown.map(o => (
              <label key={o.value} className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs hover:bg-slate-50">
                <input type="checkbox" checked={sel.has(o.value)} onChange={() => { const n = new Set(sel); n.has(o.value) ? n.delete(o.value) : n.add(o.value); onChange([...n]) }} />
                <span className={o.parent === null && o.label && !o.label.startsWith('—') && label === 'Направление' ? 'font-semibold' : ''}>{o.label}</span>
              </label>
            ))}
          </div>
          <div className="mt-1 flex justify-between border-t border-slate-100 pt-1">
            <button className="text-[11px] text-blue-700" onClick={() => onChange([])}>Сбросить</button>
            <button className="text-[11px] text-slate-600" onClick={() => setOpen(false)}>Готово</button>
          </div>
        </div>
      )}
    </div>
  )
}

const MAIN_FILTERS: [string, string][] = [['company', 'Общество'], ['direction', 'Направление'], ['service', 'Служба'], ['mclass', 'Класс МТР'], ['program', 'Программа']]
const MORE_FILTERS: [string, string][] = [['segment', 'Сегмент'], ['ownership', 'ДО/СП'], ['dgroup', 'CAPEX/OPEX'], ['warehouse', 'Склад'], ['criticality', 'Критичность'],
  ['demand_type', 'Тип спроса'], ['policy', 'Политика пополнения'], ['project', 'Проект'], ['supplier', 'Поставщик'], ['proc_model', 'Закупочная модель']]

export function TopBar({ onMenu }: { onMenu: () => void }) {
  const { meta, f, setF, setFilter, page, setPage, setAssistantOpen, setDrill } = useApp()
  const [more, setMore] = useState(false)
  const [params, setParams] = useState(false)
  const [views, setViews] = useState<any[]>([])
  const [viewsOpen, setViewsOpen] = useState(false)
  const dq = useApi<any>('/dq')
  useEffect(() => { api('/views', null).then(setViews).catch(() => { }) }, [])
  if (!meta) return null
  const months = meta.months
  const last = meta.meta.last_closed_m
  const asof = f.asof || last
  const nActive = Object.keys(f.filters).length
  const vid = page.startsWith('v') ? Number(page.slice(1)) : null
  const saveView = async () => {
    const name = prompt('Название представления', `Витрина ${vid ?? page} · ${new Date().toLocaleDateString('ru-RU')}`)
    if (!name) return
    setViews(await api('/views', null, { method: 'POST', body: { name, page, f } }))
  }
  return (
    <header className="no-print z-30 border-b border-slate-200 bg-white/95 backdrop-blur lg:sticky lg:top-0">
      <DemoBanner />
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <button className="btn lg:hidden" onClick={onMenu}>☰</button>
        {MAIN_FILTERS.map(([k, l]) => <MultiSelect key={k} label={l} options={meta.options[k] || []} value={f.filters[k] || []} onChange={v => setFilter(k, v)} />)}
        <button className="btn" onClick={() => setMore(!more)}>{more ? 'Меньше фильтров' : 'Ещё фильтры'}</button>
        <button className="btn md:hidden" onClick={() => setParams(!params)}>{params ? 'Скрыть период и параметры' : 'Период и параметры'}</button>
        {nActive > 0 && <button className="btn text-red-700" onClick={() => setF({ filters: {} })}>Сбросить фильтры ({nActive})</button>}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button className="btn-primary" onClick={() => setAssistantOpen(true)}>✦ Цифровой аналитик</button>
        </div>
      </div>
      {more && <div className="flex flex-wrap gap-2 px-3 pb-2">{MORE_FILTERS.map(([k, l]) => <MultiSelect key={k} label={l} options={meta.options[k] || []} value={f.filters[k] || []} onChange={v => setFilter(k, v)} />)}</div>}
      <div className={`${params ? 'flex' : 'hidden'} flex-wrap items-center gap-2 border-t border-slate-100 bg-slate-50 px-3 py-1.5 text-[11px] md:flex`}>
        <label className="flex items-center gap-1 text-slate-500">Дата среза
          <select className="sel" value={asof} onChange={e => setF({ asof: Number(e.target.value) })}>
            {months.slice().reverse().map((m: any) => <option key={m.m} value={m.m}>{m.label}{m.m === last ? ' (последний закрытый)' : ''}</option>)}
          </select></label>
        <label className="flex items-center gap-1 text-slate-500">Период
          <select className="sel" value={f.window} onChange={e => setF({ window: e.target.value })}>
            {['1', '3', '6', '12', '24', '36'].map(w => <option key={w} value={w}>{w === '1' ? 'месяц' : `${w} мес.`}</option>)}<option value="custom">произвольный</option>
          </select></label>
        {f.window === 'custom' && <label className="flex items-center gap-1 text-slate-500">с
          <select className="sel" value={f.start || Math.max(1, asof - 11)} onChange={e => setF({ start: Number(e.target.value) })}>
            {months.filter((m: any) => m.m <= asof).map((m: any) => <option key={m.m} value={m.m}>{m.label}</option>)}
          </select></label>}
        <label className="flex items-center gap-1 text-slate-500">Сравнение
          <select className="sel" value={f.compare} onChange={e => setF({ compare: e.target.value })}>
            <option value="prev">с предыдущим периодом</option><option value="yoy">с аналогичным периодом прошлого года</option><option value="none">без сравнения</option>
          </select></label>
        <label className="flex items-center gap-1 text-slate-500">Группировка
          <select className="sel" value={f.grain} onChange={e => setF({ grain: e.target.value })}>
            <option value="month">месяц</option><option value="quarter">квартал</option><option value="year">год</option>
          </select></label>
        <label className="flex items-center gap-1 text-slate-500">Роль
          <select className="sel max-w-[220px]" value={f.role} onChange={e => setF({ role: e.target.value, filters: {} })}>
            {meta.roles.map((r: any) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select></label>
        <span className="ml-auto flex flex-wrap items-center gap-2 text-slate-500">
          <span title={meta.meta.source}>Данные на <b className="text-slate-700">{meta.meta.last_closed_label}</b> · {meta.meta.is_demo ? 'демо-набор' : 'источник'}</span>
          {dq.data && <span className={`chip ${dq.data.summary.errors ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'}`} title="Контроль качества данных (витрина 20)">
            Качество: {dq.data.summary.errors} ошиб. · {dq.data.summary.warnings} предупр.</span>}
          <button className="btn" onClick={() => setDrill({})}>Детализация до МТР</button>
          {vid && vid <= 18 && <>
            <a className="btn" href={`/api/export/${vid}.xlsx?${query(f)}`}>Excel</a>
            <a className="btn" href={`/api/export/${vid}.pdf?${query(f)}`}>PDF</a></>}
          <button className="btn" onClick={() => window.print()}>Печать</button>
          <div className="relative">
            <button className="btn" onClick={() => setViewsOpen(!viewsOpen)}>Представления ▾</button>
            {viewsOpen && (
              <div className="absolute right-0 z-50 mt-1 w-80 rounded-md border border-slate-200 bg-white p-2 text-xs shadow-lg">
                <button className="btn-primary mb-2 w-full justify-center" onClick={saveView}>Сохранить текущее представление</button>
                {views.length === 0 && <div className="text-slate-500">Сохранённых представлений нет</div>}
                {views.map(v => (
                  <div key={v.id} className="flex items-center justify-between gap-1 border-t border-slate-100 py-1">
                    <button className="truncate text-left text-blue-700 hover:underline" onClick={() => { setF(v.f); setPage(v.page); setViewsOpen(false) }}>{v.name}</button>
                    <button className="text-slate-400 hover:text-red-600" onClick={async () => setViews(await api(`/views/${v.id}`, null, { method: 'DELETE' }))}>✕</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </span>
      </div>
    </header>
  )
}

const EXAMPLES = ['Почему увеличились НЭЗ за последние 6 месяцев?', 'Какие общества обеспечили 80% прироста запасов?', 'Какие службы имеют худшую динамику?',
  'Какие классы МТР формируют наибольшее отвлечение капитала?', 'Какие запасы можно вовлечь без риска для производства?', 'Какие закупки потенциально можно предотвратить?',
  'Как изменится структура запасов через 6 месяцев?', 'Какие три решения дадут наибольший обоснованный эффект?', 'Какие общества ухудшили оборачиваемость при росте закупок?',
  'Какие проблемы системно повторяются?']

export function AssistantPanel() {
  const { assistantOpen, setAssistantOpen, f, setDrill, setPage } = useApp()
  const [q, setQ] = useState('')
  const [hist, setHist] = useState<any[]>([])
  const [busy, setBusy] = useState(false)
  if (!assistantOpen) return null
  const ask = async (question: string) => {
    if (!question.trim()) return
    setBusy(true)
    try { const r = await api('/assistant', f, { method: 'POST', body: { question } }); setHist(h => [r, ...h]) }
    catch (e: any) { setHist(h => [{ question, summary: 'Ошибка: ' + e.message }, ...h]) }
    setBusy(false); setQ('')
  }
  const Block = ({ t, items, c }: { t: string; items: string[]; c: string }) => items?.length ? (
    <div className="mt-2"><div className={`text-[10px] font-bold uppercase tracking-wide ${c}`}>{t}</div><ul className="ml-4 list-disc space-y-0.5">{items.map((x, i) => <li key={i}>{x}</li>)}</ul></div>) : null
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30" onClick={() => setAssistantOpen(false)}>
      <div className="flex h-full w-full max-w-xl flex-col bg-white shadow-2xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div><div className="text-sm font-semibold">✦ Цифровой аналитик руководителя</div>
            <div className="text-[11px] text-slate-500">Локальный движок: проверяемые запросы и правила; языковая модель не подключена. Учитывает текущие фильтры.</div></div>
          <button className="btn" onClick={() => setAssistantOpen(false)}>✕</button>
        </div>
        <div className="border-b border-slate-200 p-3">
          <form onSubmit={e => { e.preventDefault(); ask(q) }} className="flex gap-2">
            <input className="sel flex-1 py-2 text-sm" placeholder="Задайте вопрос о запасах…" value={q} onChange={e => setQ(e.target.value)} />
            <button className="btn-primary" disabled={busy}>{busy ? '…' : 'Спросить'}</button>
          </form>
          <div className="mt-2 flex flex-wrap gap-1">{EXAMPLES.map(e => <button key={e} onClick={() => ask(e)} className="rounded-full border border-slate-200 px-2 py-0.5 text-[11px] text-slate-600 hover:bg-slate-50">{e}</button>)}</div>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-3 text-xs scroll-thin">
          {hist.map((a, i) => (
            <div key={i} className="rounded-md border border-slate-200 p-3">
              <div className="text-[11px] font-semibold text-slate-500">Вопрос: {a.question}</div>
              <div className="mt-1 text-[13px] font-medium leading-snug text-slate-900">{a.summary}</div>
              <Block t="Подтверждённые факты" items={a.facts} c="text-emerald-700" />
              <Block t="Выявленные зависимости" items={a.dependencies} c="text-amber-700" />
              <Block t="Проверяемые гипотезы" items={a.hypotheses} c="text-slate-600" />
              <Block t="Прогнозы" items={a.forecasts} c="text-blue-700" />
              <Block t="Рекомендации" items={a.recommendations} c="text-violet-700" />
              {a.table && <div className="mt-2"><DataTable spec={a.table} compact pageSize={10} /></div>}
              {a.rows?.length > 0 && <div className="mt-2">Строки данных: {a.rows.map((r: string) => <button key={r} className="mr-1 text-blue-700 underline" onClick={() => setDrill({ positionId: r })}>{r}</button>)}</div>}
              {a.period && <div className="mt-2 text-[11px] text-slate-500">Период: {a.period} · срез: {a.asof} · источники: {a.sources?.join(', ')}</div>}
              {a.limitations?.length > 0 && <div className="mt-1 text-[11px] text-slate-500">Ограничения: {a.limitations.join(' ')}</div>}
              {a.vitrine && <button className="mt-1 text-[11px] text-blue-700 hover:underline" onClick={() => { setPage(`v${a.vitrine}`); setAssistantOpen(false) }}>Открыть витрину {a.vitrine} →</button>}
              {a.engine && <div className="mt-1 text-[10px] text-slate-400">{a.engine}</div>}
            </div>
          ))}
          {hist.length === 0 && <div className="text-slate-500">Выберите пример или задайте свой вопрос. Ответ содержит расчёт, источник, период, ограничения и ссылки на строки данных.</div>}
        </div>
      </div>
    </div>
  )
}

export function PageHeader({ title, desc, right }: { title: string; desc?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
      <div><h1 className="text-lg font-semibold tracking-tight text-slate-900">{title}</h1>{desc && <p className="text-xs text-slate-500">{desc}</p>}</div>
      {right}
    </div>
  )
}
