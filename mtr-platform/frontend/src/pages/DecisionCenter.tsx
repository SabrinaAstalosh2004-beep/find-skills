import { useMemo, useState } from 'react'
import { api, fmt, money } from '../lib'
import { useApi, useApp } from '../state'
import { DataTable } from '../components/DataTable'
import { PageHeader } from '../components/Layout'
import { ErrorBox, InsightCard, KpiCard, Modal, Spinner } from '../components/ui'

export function DecisionCenter() {
  const [tab, setTab] = useState<'issues' | 'actions' | 'dq'>('issues')
  return (
    <div>
      <PageHeader title="20. Центр управленческих решений и контроля исполнения"
        desc="Единый перечень проблем → мероприятия → контроль исполнения и эффекта. Ответственный и срок не придумываются: пустые значения — «Требует назначения»."
        right={<span className="chip bg-amber-100 text-amber-800">ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ</span>} />
      <div className="mb-3 flex gap-1 border-b border-slate-200 text-xs">
        {[['issues', 'Проблемы (аналитический механизм)'], ['actions', 'Реестр мероприятий'], ['dq', 'Качество данных']].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k as any)} className={`-mb-px border-b-2 px-3 py-2 font-medium ${tab === k ? 'border-blue-700 text-blue-800' : 'border-transparent text-slate-500 hover:text-slate-800'}`}>{l}</button>
        ))}
      </div>
      {tab === 'issues' && <Issues />}
      {tab === 'actions' && <Actions />}
      {tab === 'dq' && <DQ />}
    </div>
  )
}

function Issues() {
  const { f, bump } = useApp()
  const ins = useApi<any>('/insights')
  const acts = useApi<any>('/actions')
  const [kind, setKind] = useState('all')
  const [msg, setMsg] = useState<string | null>(null)
  if (ins.err) return <ErrorBox msg={ins.err} />
  if (!ins.data || !acts.data) return <Spinner />
  const reg = new Map<string, any>(acts.data.actions.filter((a: any) => a.issue_key).map((a: any) => [a.issue_key, a]))
  const items = ins.data.insights.filter((i: any) => i.type !== 'engine_error' && (kind === 'all' || i.kind === kind))
  const accept = async (i: any) => {
    try { const r = await api('/actions', f, { method: 'POST', body: { insight_id: i.id } }); setMsg(`Создано мероприятие ${r.action_id}; ответственный: ${r.owner}; срок: требует утверждения`); bump() }
    catch (e: any) { setMsg(e.message) }
  }
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-slate-500">Рейтинг по критичности и потенциальной ценности ({items.length})</span>
        <select className="sel" value={kind} onChange={e => setKind(e.target.value)}><option value="all">Все</option><option>Аномалия</option><option>Закономерность</option></select>
        {msg && <span className="rounded bg-emerald-50 px-2 py-1 text-emerald-800">{msg}</span>}
      </div>
      <div className="grid gap-2 md:grid-cols-2 2xl:grid-cols-3">
        {items.map((i: any, n: number) => (
          <div key={i.id} className="relative">
            <span className="absolute -left-1 -top-1 z-10 rounded-full bg-slate-800 px-1.5 text-[10px] font-bold text-white">{n + 1}</span>
            <InsightCard i={i} onAccept={reg.has(i.id) ? undefined : accept} />
            {reg.has(i.id) && <div className="mt-1 rounded bg-blue-50 px-2 py-1 text-[11px] text-blue-800">В реестре: {reg.get(i.id).action_id} · {reg.get(i.id).effective_status}{reg.get(i.id).repeat_count > 1 ? ` · повторяется (${reg.get(i.id).repeat_count})` : ''}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

function Actions() {
  const { f, bump } = useApp()
  const { data, err } = useApi<any>('/actions')
  const [st, setSt] = useState('all')
  const [edit, setEdit] = useState<any>(null)
  const [newOpen, setNewOpen] = useState(false)
  const rows = useMemo(() => {
    if (!data) return []
    const order: Record<string, number> = { 'Высокая': 0, 'Средняя': 1, 'Низкая': 2 }
    return data.actions.filter((a: any) => st === 'all' || a.effective_status === st)
      .sort((a: any, b: any) => (order[a.criticality] ?? 3) - (order[b.criticality] ?? 3) || (b.value_at_risk || 0) - (a.value_at_risk || 0))
      .map((a: any) => ({ ...a, repeat: a.repeat_count > 1 ? `Повтор ×${a.repeat_count}` : '' }))
  }, [data, st])
  if (err) return <ErrorBox msg={err} />
  if (!data) return <Spinner />
  const s = data.stats
  return (
    <div>
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
        <KpiCard k={{ label: 'Всего мероприятий', value: s.total, unit: 'count' }} />
        <KpiCard k={{ label: 'Просрочено', value: s.overdue, unit: 'count', status: s.overdue ? 'bad' : 'ok' }} />
        <KpiCard k={{ label: 'Требует назначения', value: s.tbd, unit: 'count', status: s.tbd ? 'bad' : 'ok' }} />
        <KpiCard k={{ label: 'В работе', value: s.in_work, unit: 'count' }} />
        <KpiCard k={{ label: 'Выполнено', value: s.done, unit: 'count' }} />
        <KpiCard k={{ label: 'Повторяющиеся проблемы', value: s.repeated, unit: 'count' }} />
        <KpiCard k={{ label: 'Прогнозный эффект', value: s.forecast, unit: 'rub' }} />
        <KpiCard k={{ label: 'Фактический эффект (подтв.)', value: s.actual, unit: 'rub' }} />
      </div>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <select className="sel" value={st} onChange={e => setSt(e.target.value)}><option value="all">Все статусы</option>{data.statuses.map((x: string) => <option key={x}>{x}</option>)}</select>
        <button className="btn-primary" onClick={() => setNewOpen(true)}>+ Мероприятие вручную</button>
        <span className="text-slate-500">Нажмите на строку для изменения статуса, ответственного, срока и фактического эффекта</span>
      </div>
      <div className="card p-3">
        <DataTable onRow={r => setEdit(r)} pageSize={30} spec={{ rows, columns: [
          { key: 'action_id', label: '№', type: 'text' }, { key: 'company_name', label: 'Общество', type: 'text' }, { key: 'direction_id', label: 'Направл.', type: 'text' },
          { key: 'mclass', label: 'Класс МТР', type: 'text' }, { key: 'title', label: 'Проблема / мероприятие', type: 'text' }, { key: 'value_at_risk', label: 'Сумма под риском', type: 'money' },
          { key: 'cause', label: 'Причина', type: 'text' }, { key: 'cause_status', label: 'Статус причины', type: 'status' }, { key: 'evidence', label: 'Доказательная база', type: 'text' },
          { key: 'measure', label: 'Мероприятие', type: 'text' }, { key: 'owner_display', label: 'Ответственный', type: 'text' }, { key: 'deadline_display', label: 'Срок', type: 'text' },
          { key: 'forecast_effect', label: 'Прогноз результата', type: 'money' }, { key: 'actual_effect', label: 'Факт', type: 'money' },
          { key: 'effective_status', label: 'Статус', type: 'status' }, { key: 'criticality', label: 'Критичность', type: 'status' }, { key: 'repeat', label: 'Повтор', type: 'status' },
          { key: 'acceptance', label: 'Критерий приёмки', type: 'text' }] }} />
      </div>
      {edit && <EditAction a={edit} statuses={data.statuses} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); bump() }} />}
      {newOpen && <NewAction onClose={() => setNewOpen(false)} onSaved={() => { setNewOpen(false); bump() }} />}
    </div>
  )
}

function EditAction({ a, statuses, onClose, onSaved }: any) {
  const { f } = useApp()
  const [v, setV] = useState({ owner: a.owner === 'Требует назначения' ? '' : a.owner, deadline: a.deadline || '', status: a.status, actual_effect: a.actual_effect ?? '', comment: a.comment || '' })
  const [err, setErr] = useState<string | null>(null)
  const save = async () => {
    try {
      await api(`/actions/${a.action_id}`, f, { method: 'PATCH', body: { owner: v.owner || 'Требует назначения', deadline: v.deadline || null, status: v.status,
        actual_effect: v.actual_effect === '' ? null : Number(v.actual_effect), comment: v.comment } })
      onSaved()
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <Modal title={`${a.action_id}: ${a.title}`} onClose={onClose}>
      <div className="grid gap-2 text-xs sm:grid-cols-2">
        <div className="sm:col-span-2 text-slate-600">{a.deviation}<br /><b>Причина:</b> {a.cause} [{a.cause_status}]<br /><b>Доказательства:</b> {a.evidence || '—'}</div>
        <label>Ответственный (по матрице полномочий)<input className="sel mt-1 w-full" value={v.owner} placeholder="Требует назначения" onChange={e => setV({ ...v, owner: e.target.value })} /></label>
        <label>Утверждённый срок<input type="date" className="sel mt-1 w-full" value={v.deadline} onChange={e => setV({ ...v, deadline: e.target.value })} /></label>
        <label>Статус<select className="sel mt-1 w-full" value={v.status} onChange={e => setV({ ...v, status: e.target.value })}>{statuses.map((s: string) => <option key={s}>{s}</option>)}</select></label>
        <label>Фактический эффект, ₽<input type="number" className="sel mt-1 w-full" value={v.actual_effect} onChange={e => setV({ ...v, actual_effect: e.target.value })} /></label>
        <label className="sm:col-span-2">Комментарий<textarea className="sel mt-1 w-full" rows={2} value={v.comment} onChange={e => setV({ ...v, comment: e.target.value })} /></label>
        <div className="sm:col-span-2 text-slate-500">Критерий приёмки: {a.acceptance || '—'}. Прогноз: {money(a.forecast_effect)}.</div>
        {err && <div className="sm:col-span-2 text-red-600">{err}</div>}
        <div className="sm:col-span-2"><button className="btn-primary" onClick={save}>Сохранить</button></div>
      </div>
    </Modal>
  )
}

function NewAction({ onClose, onSaved }: any) {
  const { f, meta } = useApp()
  const [v, setV] = useState<any>({ title: '', measure: '', company_id: '', owner: '', deadline: '', acceptance: '' })
  const save = async () => { await api('/actions', f, { method: 'POST', body: { ...v, deadline: v.deadline || null } }); onSaved() }
  return (
    <Modal title="Новое мероприятие" onClose={onClose}>
      <div className="grid gap-2 text-xs sm:grid-cols-2">
        <label className="sm:col-span-2">Проблема<input className="sel mt-1 w-full" value={v.title} onChange={e => setV({ ...v, title: e.target.value })} /></label>
        <label className="sm:col-span-2">Мероприятие<input className="sel mt-1 w-full" value={v.measure} onChange={e => setV({ ...v, measure: e.target.value })} /></label>
        <label>Общество<select className="sel mt-1 w-full" value={v.company_id} onChange={e => setV({ ...v, company_id: e.target.value })}><option value="">—</option>{meta.options.company.map((c: any) => <option key={c.value} value={c.value}>{c.label}</option>)}</select></label>
        <label>Ответственный<input className="sel mt-1 w-full" placeholder="Требует назначения" value={v.owner} onChange={e => setV({ ...v, owner: e.target.value })} /></label>
        <label>Срок (если утверждён)<input type="date" className="sel mt-1 w-full" value={v.deadline} onChange={e => setV({ ...v, deadline: e.target.value })} /></label>
        <label>Критерий приёмки<input className="sel mt-1 w-full" value={v.acceptance} onChange={e => setV({ ...v, acceptance: e.target.value })} /></label>
        <div className="sm:col-span-2"><button className="btn-primary" disabled={!v.title} onClick={save}>Создать</button></div>
      </div>
    </Modal>
  )
}

function DQ() {
  const { data, err } = useApi<any>('/dq')
  const [open, setOpen] = useState<string | null>(null)
  if (err) return <ErrorBox msg={err} />
  if (!data) return <Spinner />
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2 md:w-1/2">
        <KpiCard k={{ label: 'Ошибки', value: data.summary.errors, unit: 'count', status: data.summary.errors ? 'bad' : 'ok' }} />
        <KpiCard k={{ label: 'Предупреждения', value: data.summary.warnings, unit: 'count' }} />
        <KpiCard k={{ label: 'Проверок пройдено', value: data.summary.ok, unit: 'count', status: 'ok' }} />
      </div>
      <p className="text-[11px] text-slate-500">{data.note}</p>
      <div className="card divide-y divide-slate-100">
        {data.checks.map((c: any) => (
          <div key={c.id} className="p-2 text-xs">
            <div className="flex cursor-pointer flex-wrap items-center gap-2" onClick={() => setOpen(open === c.id ? null : c.id)}>
              <span className={`chip ${c.status === 'OK' ? 'bg-emerald-100 text-emerald-700' : c.status === 'Ошибка' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-800'}`}>{c.status}</span>
              <span className="w-48 text-slate-500">{c.group}</span><span className="flex-1 font-medium">{c.check}</span>
              <span className="tabular-nums">{fmt(c.count, 'int')} нарушений</span><span className="text-slate-400">{c.severity}</span>
            </div>
            <div className="mt-0.5 pl-1 text-[11px] text-slate-500">{c.description}</div>
            {open === c.id && c.sample.length > 0 && <div className="mt-2"><DataTable compact spec={{ columns: Object.keys(c.sample[0]).map(k => ({ key: k, label: k, type: typeof c.sample[0][k] === 'number' ? 'num' : 'text' })), rows: c.sample }} /></div>}
          </div>
        ))}
      </div>
      <div className="card p-3">
        <div className="mb-2 text-[13px] font-semibold">Источники: актуальность, полнота, статус</div>
        <DataTable spec={{ columns: [{ key: 'name', label: 'Набор данных', type: 'text' }, { key: 'table', label: 'Таблица', type: 'text' }, { key: 'rows', label: 'Строк', type: 'int' },
          { key: 'period', label: 'Период', type: 'text' }, { key: 'source', label: 'Источник', type: 'text' }, { key: 'loaded_at', label: 'Загружено', type: 'text' },
          { key: 'completeness', label: 'Полнота', type: 'text' }, { key: 'status', label: 'Статус', type: 'status' }], rows: data.sources }} />
      </div>
    </div>
  )
}
