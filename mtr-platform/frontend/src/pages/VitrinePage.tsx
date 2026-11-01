import { useEffect, useState } from 'react'
import { Q_TITLES } from '../lib'
import { useApi, useApp } from '../state'
import { PageHeader } from '../components/Layout'
import { ErrorBox, InsightsPanel, KpiCard, Section, Spinner } from '../components/ui'

const ORDER = ['what', 'where', 'why', 'risk', 'action']

export function VitrinePage({ vid }: { vid: number }) {
  const [opts, setOpts] = useState<Record<string, string>>({})
  useEffect(() => setOpts({}), [vid])
  const extra = Object.fromEntries(Object.entries(opts).map(([k, v]) => [`o_${k}`, v]))
  const { data, loading, err } = useApi<any>(`/vitrine/${vid}`, extra, [vid])
  const [panel, setPanel] = useState(true)
  if (err) return <ErrorBox msg={err} />
  if (!data) return <Spinner />
  const byQ: Record<string, any[]> = {}
  data.sections.forEach((s: any) => { (byQ[s.q] = byQ[s.q] || []).push(s) })
  return (
    <div className={`flex gap-3 ${loading ? 'opacity-60 transition-opacity' : ''}`}>
      <div className="min-w-0 flex-1">
        <PageHeader title={`${data.id}. ${data.title}`}
          desc={<>{data.description} · период <b>{data.ctx.period}</b>{data.ctx.compare_period ? <> · сравнение: {data.ctx.compare_period}</> : null} · срез на {data.ctx.asof_label}
            {Object.keys(data.ctx.filters).length > 0 && <> · фильтры: {Object.entries(data.ctx.filters).map(([k, v]: any) => `${k}=${v.join(',')}`).join('; ')}</>}
            {data.is_demo && <span className="chip ml-2 bg-amber-100 text-amber-800">ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ</span>}</>}
          right={<button className="btn no-print hidden xl:inline-flex" onClick={() => setPanel(!panel)}>{panel ? 'Скрыть панель отклонений' : 'Показать отклонения'} ({data.insights.length})</button>} />
        {data.kpis.length > 0 && <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">{data.kpis.map((k: any) => <KpiCard key={k.id} k={k} />)}</div>}
        {ORDER.filter(q => byQ[q]).map(q => (
          <section key={q} className="mb-4">
            <h2 className="mb-2 flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-slate-500"><span className="h-px w-4 bg-slate-300" />{Q_TITLES[q]}<span className="h-px flex-1 bg-slate-200" /></h2>
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
              {byQ[q].map(s => <Section key={s.id} s={s} onControl={(k, v) => setOpts(o => ({ ...o, [k]: v }))} />)}
            </div>
          </section>
        ))}
        <div className="xl:hidden"><InsightsPanel items={data.insights} /></div>
        <p className="mt-4 text-[11px] text-slate-400">Расчёт: {data.elapsed} с · методики — рабочие (демо), требуют подтверждения корпоративной методологией · источник: {data.data_meta.source}</p>
      </div>
      {panel && <div className="no-print hidden w-80 shrink-0 xl:block"><div className="sticky top-28 max-h-[calc(100vh-8rem)] overflow-y-auto pr-1 scroll-thin"><InsightsPanel items={data.insights} /></div></div>}
    </div>
  )
}
