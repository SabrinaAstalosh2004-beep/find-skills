import { useState } from 'react'
import { api } from '../lib'
import { useApi, useApp } from '../state'
import { Chart } from '../components/Chart'
import { DataTable } from '../components/DataTable'
import { PageHeader } from '../components/Layout'
import { ErrorBox, Spinner } from '../components/ui'

export function SliceBuilder() {
  const { meta, setDrill } = useApp()
  const [s, setS] = useState({ metric: 'nez_end', dim1: 'company', dim2: '', chart: 'bar', sort: 'desc', top: '20' })
  const { data, loading, err } = useApi<any>('/slice', s)
  if (!meta) return null
  const dims = meta.dimensions
  const set = (k: string, v: string) => setS({ ...s, [k]: v })
  return (
    <div>
      <PageHeader title="Универсальный конструктор срезов" desc="Показатель × разрез × второй разрез × период × тип визуализации. Сквозные фильтры и период — в верхней панели." />
      <div className="card mb-3 flex flex-wrap items-end gap-3 p-3 text-xs">
        <label>Показатель<br /><select className="sel" value={s.metric} onChange={e => set('metric', e.target.value)}>{meta.metrics.map((m: any) => <option key={m.id} value={m.id}>{m.label}</option>)}</select></label>
        <label>Разрез<br /><select className="sel" value={s.dim1} onChange={e => set('dim1', e.target.value)}><option value="time">⏱ Время (динамика)</option>{dims.map((d: any) => <option key={d.key} value={d.key}>{d.label}</option>)}</select></label>
        <label>Второй разрез<br /><select className="sel" value={s.dim2} onChange={e => set('dim2', e.target.value)}><option value="">—</option>{dims.filter((d: any) => !['age_bucket', 'noissue_bucket'].includes(d.key)).map((d: any) => <option key={d.key} value={d.key}>{d.label}</option>)}</select></label>
        <label>Визуализация<br /><select className="sel" value={s.chart} onChange={e => set('chart', e.target.value)}>
          {[['bar', 'Столбцы'], ['hbar', 'Горизонтальные столбцы'], ['grouped', 'Группированные'], ['stacked', 'С накоплением'], ['line', 'Линия (для времени)'], ['heatmap', 'Тепловая карта (2 разреза)'], ['pareto', 'Парето'], ['treemap', 'Treemap']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label>Сортировка<br /><select className="sel" value={s.sort} onChange={e => set('sort', e.target.value)}><option value="desc">по убыванию</option><option value="asc">по возрастанию</option></select></label>
        <label>Глубина<br /><select className="sel" value={s.top} onChange={e => set('top', e.target.value)}>{['10', '20', '50'].map(x => <option key={x}>{x}</option>)}</select></label>
        <span className="text-slate-500">Пример: «НЭЗ × Время × Общество», фильтры: Служба = Механическая, CAPEX, Класс = Насосное оборудование, период 24 мес.</span>
      </div>
      {err && <ErrorBox msg={err} />}{loading && !data && <Spinner />}
      {data && (
        <div className={`space-y-3 ${loading ? 'opacity-60' : ''}`}>
          {data.metric && <div className="text-[11px] text-slate-500"><b>{data.metric.label}</b>: {data.metric.formula}{data.metric.limitations ? ` · ${data.metric.limitations}` : ''}</div>}
          <div className="card p-3"><Chart spec={data.chart} onClick={p => {
            if (s.dim1 === 'time') return
            const opts = meta.options[s.dim1]
            const v = opts ? opts.find((o: any) => o.label.replace(/^— /, '') === p.name)?.value : p.name
            if (v) setDrill({ dim: s.dim1, value: v, label: p.name })
          }} /></div>
          <div className="card p-3"><DataTable spec={data.table} onRow={s.dim1 !== 'time' ? r => setDrill({ dim: s.dim1, value: r[s.dim1], label: r[`${s.dim1}_label`] }) : undefined} /></div>
        </div>
      )}
    </div>
  )
}

export function Methodology() {
  const { f, bump } = useApp()
  const { data, err } = useApi<any>('/metrics')
  const [patch, setPatch] = useState<any>(null)
  const [msg, setMsg] = useState<string | null>(null)
  if (err) return <ErrorBox msg={err} />
  if (!data) return <Spinner />
  const s = patch || data.settings
  const upd = (path: string[], v: any) => {
    const n = JSON.parse(JSON.stringify(s))
    let o = n
    path.slice(0, -1).forEach(k => { o = o[k] })
    o[path[path.length - 1]] = v
    setPatch(n)
  }
  const save = async () => {
    try { await api('/settings', f, { method: 'PUT', body: s }); setMsg('Параметры применены, представления пересчитаны'); setPatch(null); bump() }
    catch (e: any) { setMsg(e.message) }
  }
  const reset = async () => { await api('/settings/reset', f, { method: 'POST' }); setPatch(null); setMsg('Восстановлены параметры по умолчанию'); bump() }
  const Num = ({ label, path, step = 1 }: { label: string; path: string[]; step?: number }) => {
    let v: any = s
    path.forEach(k => { v = v?.[k] })
    return <label className="text-xs">{label}<input type="number" step={step} className="sel mt-1 block w-full" value={v} onChange={e => upd(path, Number(e.target.value))} /></label>
  }
  return (
    <div className="space-y-3">
      <PageHeader title="Методика, целевые значения и каталог метрик" desc={s.methodology_status} />
      <div className="card p-3">
        <div className="mb-2 text-[13px] font-semibold">Настраиваемые правила и цели</div>
        <p className="mb-2 text-[11px] text-amber-700">Пороги (в т.ч. 90/180/365 дней), цели и правила признания НЭЗ не являются действующими нормами без документального подтверждения
          (ОСК-03.06.04 v3.0 в систему не загружен). Изменение доступно ролям группового уровня.</p>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          <Num label="НЭЗ: дней без потребления ≥" path={['nez', 'no_issue_days']} />
          <label className="text-xs">НЭЗ: горизонт подтверждённой потребности, мес.<select className="sel mt-1 block w-full" value={s.nez.need_horizon_months} onChange={e => upd(['nez', 'need_horizon_months'], Number(e.target.value))}>{[3, 6, 12, 24].map(x => <option key={x}>{x}</option>)}</select></label>
          <Num label="«Без потребления» — порог, дн." path={['no_consumption_days']} />
          <Num label="Цель: доля НЭЗ, %" path={['targets', 'nez_share_pct']} step={0.5} />
          <Num label="Цель: оборачиваемость, дн." path={['targets', 'turnover_days']} />
          <Num label="Цель: рост запасов за год, %" path={['targets', 'stock_growth_pct_year']} step={0.5} />
          <Num label="Цель: риск дефицита, млн ₽" path={['targets', 'deficit_value_mln']} />
          <Num label="Стоимость капитала (доля)" path={['finance', 'cost_of_capital']} step={0.01} />
          <Num label="Ставка хранения (доля)" path={['finance', 'storage_rate']} step={0.01} />
          <Num label="Моральный износ (доля)" path={['finance', 'obsolescence_rate']} step={0.01} />
          <Num label="Уровень обслуживания ЗИП" path={['zip', 'service_level']} step={0.01} />
          <Num label="Избыточное покрытие, мес." path={['coverage_excess_months']} />
          <Num label="Горизонт дефицита, мес." path={['deficit_horizon_months']} />
          <Num label="Транспорт, доля стоимости" path={['redistribution', 'transport_cost_pct']} step={0.005} />
        </div>
        <div className="mt-2 text-[11px] text-slate-500">Исключения из НЭЗ: политики «{s.nez.protected_policies.join(', ')}», критичность «{s.nez.protected_criticality.join(', ')}». {s.nez.note}</div>
        <div className="mt-3 flex gap-2"><button className="btn-primary" disabled={!patch} onClick={save}>Применить и пересчитать</button><button className="btn" onClick={reset}>Сбросить к умолчанию</button>{msg && <span className="text-xs text-emerald-700">{msg}</span>}</div>
      </div>
      <div className="card p-3">
        <div className="mb-2 text-[13px] font-semibold">Единый каталог метрик ({data.metrics.length})</div>
        <DataTable pageSize={50} spec={{ rows: data.metrics, columns: [{ key: 'group', label: 'Группа', type: 'text' }, { key: 'label', label: 'Наименование', type: 'text' },
          { key: 'formula', label: 'Формула', type: 'text' }, { key: 'unit', label: 'Ед.', type: 'text' }, { key: 'source', label: 'Источник', type: 'text' }, { key: 'period', label: 'Период', type: 'text' },
          { key: 'aggregation', label: 'Агрегация', type: 'text' }, { key: 'includes', label: 'Включения', type: 'text' }, { key: 'excludes', label: 'Исключения', type: 'text' },
          { key: 'limitations', label: 'Ограничения', type: 'text' }, { key: 'owner', label: 'Ответственный за методологию', type: 'text' }, { key: 'status', label: 'Статус методики', type: 'status' }] }} />
      </div>
    </div>
  )
}

export function Sources() {
  const { f, bump } = useApp()
  const { data, err } = useApi<any>('/sources')
  const [tbl, setTbl] = useState('snapshot')
  const [file, setFile] = useState<File | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  if (err) return <ErrorBox msg={err} />
  if (!data) return <Spinner />
  const upload = async () => {
    if (!file) return
    const fd = new FormData()
    fd.append('table_name', tbl)
    fd.append('file', file)
    const r = await fetch('/api/sources/upload', { method: 'POST', body: fd })
    const j = await r.json()
    setMsg(r.ok ? `Загружено в staging: ${j.table}, строк ${j.rows}` : `Ошибка: ${j.detail}`)
    bump()
  }
  const act = async (path: string) => {
    try { const r = await api(path, f, { method: 'POST' }); setMsg(r.ok ? 'Готово: данные перезагружены' : r.error); bump() } catch (e: any) { setMsg(e.message) }
  }
  return (
    <div className="space-y-3">
      <PageHeader title="Источники данных и интеграции" desc={`Активный источник: ${data.is_demo ? 'демонстрационный набор' : data.active}. Готовые API корпоративных систем не придумываются — используются адаптеры и выгрузки в каноническом формате.`} />
      <div className="card p-3">
        <DataTable spec={{ rows: data.adapters, columns: [{ key: 'name', label: 'Адаптер / система', type: 'text' }, { key: 'description', label: 'Назначение', type: 'text' },
          { key: 'status', label: 'Статус', type: 'status' }] }} />
      </div>
      <div className="card p-3 text-xs">
        <div className="mb-2 text-[13px] font-semibold">Загрузка фактических данных (CSV / Excel / Parquet)</div>
        <div className="flex flex-wrap items-end gap-2">
          <label>Каноническая таблица<br /><select className="sel" value={tbl} onChange={e => setTbl(e.target.value)}>{Object.keys(data.schema).map(t => <option key={t}>{t}</option>)}</select></label>
          <input type="file" accept=".csv,.xlsx,.parquet" onChange={e => setFile(e.target.files?.[0] || null)} />
          <button className="btn-primary" disabled={!file} onClick={upload}>Проверить и загрузить</button>
          <button className="btn" onClick={() => act('/sources/activate')}>Активировать загруженный набор</button>
          <button className="btn" onClick={() => act('/sources/reset-demo')}>Вернуть демонстрационный набор</button>
        </div>
        {msg && <div className="mt-2 rounded bg-slate-100 p-2">{msg}</div>}
        <div className="mt-2 text-slate-500">Загружено в staging: {data.staged.join(', ') || 'нет'}. Не хватает: {data.missing.join(', ') || '—'}.</div>
        <div className="mt-3 font-semibold">Обязательные колонки таблицы «{tbl}»</div>
        <div className="mt-1 flex flex-wrap gap-1">{(data.schema[tbl] || []).map((c: any) => <span key={c.column} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px]">{c.column}: {c.type}</span>)}</div>
      </div>
      <div className="card p-3">
        <div className="mb-2 text-[13px] font-semibold">Статус наборов данных</div>
        <DataTable spec={{ rows: data.status, columns: [{ key: 'name', label: 'Набор', type: 'text' }, { key: 'rows', label: 'Строк', type: 'int' }, { key: 'period', label: 'Период', type: 'text' },
          { key: 'loaded_at', label: 'Загружено', type: 'text' }, { key: 'completeness', label: 'Полнота', type: 'text' }, { key: 'status', label: 'Статус', type: 'status' }] }} />
      </div>
    </div>
  )
}
