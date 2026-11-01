import { useEffect, useMemo, useRef, useState } from 'react'
import { api, fmt, money } from '../lib'
import { useApp } from '../state'
import { Chart } from '../components/Chart'
import { DataTable } from '../components/DataTable'
import { PageHeader } from '../components/Layout'
import { ErrorBox, KpiCard, Spinner } from '../components/ui'

export function ScenarioPage() {
  const { f, version } = useApp()
  const [meta, setMeta] = useState<any[] | null>(null)
  const [p, setP] = useState<Record<string, number>>({})
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const timer = useRef<any>(null)
  useEffect(() => { api('/scenarios/defaults', null).then(d => { setMeta(d.params); setP(Object.fromEntries(d.params.map((x: any) => [x.key, x.default]))) }) }, [])
  useEffect(() => {
    if (!meta) return
    clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      setBusy(true)
      try { setRes(await api('/scenarios/compute', f, { method: 'POST', body: { params: p } })); setErr(null) } catch (e: any) { setErr(e.message) }
      setBusy(false)
    }, 350)
  }, [JSON.stringify(p), JSON.stringify(f), version, meta])
  const groups = useMemo(() => meta ? Array.from(new Set(meta.map(m => m.group))) : [], [meta])
  if (!meta) return <Spinner />
  const t = res?.totals
  return (
    <div>
      <PageHeader title="19. Экономика управления запасами и сценарное моделирование"
        desc="Параметры изменяются — расчёт пересчитывается на сервере. Эффекты считаются относительно базового сценария; рычаги разделяют общие пулы запасов, поэтому двойной счёт исключён."
        right={<span className="chip bg-amber-100 text-amber-800">ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ</span>} />
      <div className="flex flex-col gap-3 lg:flex-row">
        <div className="card w-full shrink-0 p-3 lg:w-80">
          <div className="mb-2 flex items-center justify-between"><div className="text-xs font-semibold">Параметры сценария</div>
            <button className="btn" onClick={() => setP(Object.fromEntries(meta.map((x: any) => [x.key, x.default])))}>По умолчанию</button></div>
          <div className="max-h-[75vh] space-y-3 overflow-y-auto pr-1 scroll-thin">
            {groups.map(g => (
              <div key={g}>
                <div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-500">{g}</div>
                {meta.filter(m => m.group === g).map(m => (
                  <div key={m.key} className="mb-2">
                    <div className="flex justify-between text-[11px] text-slate-600"><span className="pr-2">{m.label}</span><b className="tabular-nums">{p[m.key]}{m.unit && m.unit !== '' ? ` ${m.unit}` : ''}</b></div>
                    <input type="range" className="w-full accent-blue-700" min={m.min} max={m.max} step={m.step} value={p[m.key] ?? m.default} onChange={e => setP({ ...p, [m.key]: Number(e.target.value) })} />
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
        <div className={`min-w-0 flex-1 space-y-3 ${busy ? 'opacity-70' : ''}`}>
          {err && <ErrorBox msg={err} />}
          {!res && <Spinner />}
          {res && t && (
            <>
              <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
                <KpiCard k={{ label: '1. Высвобождение оборотного капитала', value: t.wc_release, unit: 'rub', sub: `P10–P90: ${money(res.uncertainty.wc_release.p10)} – ${money(res.uncertainty.wc_release.p90)}` }} />
                <KpiCard k={{ label: '2. Изменение денежного потока', value: t.cash_flow, unit: 'rub', sub: `P10–P90: ${money(res.uncertainty.cash_flow.p10)} – ${money(res.uncertainty.cash_flow.p90)}` }} />
                <KpiCard k={{ label: '3. Предотвращённые закупки', value: t.avoided_purchases, unit: 'rub', note: 'Входит в денежный поток; не суммируется с ним' }} />
                <KpiCard k={{ label: '4. Снижение операционных расходов', value: t.opex_reduction, unit: 'rub', note: 'Хранение и моральный износ на высвобожденный запас' }} />
                <KpiCard k={{ label: '5. Фактический эффект (реестр)', value: res.actual_effect, unit: 'rub', sub: 'Подтверждённые мероприятия' }} />
                <KpiCard k={{ label: '6. Прогнозный экономический эффект', value: t.forecast_effect, unit: 'rub', sub: 'Денежный поток + снижение расходов' }} />
                <KpiCard k={{ label: '7. Влияние на EBITDA', value: t.ebitda, unit: 'rub', note: 'Только операционные расходы и затраты внедрения; высвобождение капитала и стоимость капитала в EBITDA не входят' }} />
                <KpiCard k={{ label: '8. Стоимость внедрения', value: t.implementation_cost, unit: 'rub' }} />
                <KpiCard k={{ label: 'Запасы через горизонт: база', value: res.base.stock_horizon, unit: 'rub', sub: res.base.formula }} />
                <KpiCard k={{ label: 'Запасы через горизонт: сценарий', value: res.scenario_stock, unit: 'rub', sub: `Изменение к базе ${money(res.scenario_stock - res.base.stock_horizon)}` }} />
              </div>
              <div className="grid gap-3 xl:grid-cols-2">
                <div className="card p-3"><div className="mb-1 text-[13px] font-semibold">Запасы на горизонте: базовый сценарий → рычаги → сценарий</div>
                  <Chart spec={{ kind: 'waterfall', unit: 'rub', items: [{ name: 'База', value: res.base.stock_horizon, type: 'total' },
                    ...res.levers.filter((l: any) => l.wc_release > 0).map((l: any) => ({ name: l.name, value: -l.wc_release, type: 'delta' })),
                    { name: 'Сценарий', value: res.scenario_stock, type: 'total' }] }} /></div>
                <div className="card p-3"><div className="mb-1 text-[13px] font-semibold">Сравнение вариантов</div>
                  <Chart spec={{ kind: 'bar', unit: 'rub', categories: res.variants.map((v: any) => v.name), series: [
                    { name: 'Высвобождение капитала', data: res.variants.map((v: any) => v.wc_release) }, { name: 'Денежный поток', data: res.variants.map((v: any) => v.cash_flow) },
                    { name: 'Снижение расходов', data: res.variants.map((v: any) => v.opex_reduction) }, { name: 'EBITDA', data: res.variants.map((v: any) => v.ebitda) }] }} />
                  <p className="text-[11px] text-slate-500">{res.uncertainty.method}</p></div>
              </div>
              <div className="card p-3">
                <div className="mb-2 text-[13px] font-semibold">Расчёт по рычагам: исходные данные, формула, допущения, ограничения, риски</div>
                <DataTable spec={{ columns: [{ key: 'name', label: 'Решение', type: 'text' }, { key: 'wc_release', label: 'Высвобождение капитала', type: 'money' },
                  { key: 'avoided_purchases', label: 'Предотвращ. закупки', type: 'money' }, { key: 'cash_flow', label: 'Денежный поток', type: 'money' },
                  { key: 'opex_reduction', label: 'Снижение расходов', type: 'money' }, { key: 'implementation_cost', label: 'Внедрение', type: 'money' },
                  { key: 'ebitda', label: 'EBITDA', type: 'money' }, { key: 'risk', label: 'Производственные/финансовые риски', type: 'text' },
                  { key: 'formula', label: 'Формула', type: 'text' }, { key: 'inputs', label: 'Исходные данные', type: 'text' }, { key: 'assumptions', label: 'Допущения', type: 'text' },
                  { key: 'limitations', label: 'Ограничения', type: 'text' }], rows: res.levers, total: res.totals }} pageSize={20} />
              </div>
              <div className="card p-3 text-[11px] text-slate-600">
                <b>Пулы запасов (исходные данные):</b> избыточное покрытие {money(res.pools.excess)}; свободный излишек сверх потребности 12 мес. {money(res.pools.surplus)};
                НЭЗ с потребностью в других обществах {money(res.pools.nez_demand)}; матрица перераспределения {money(res.pools.redist_value)}; кандидаты на отмену заказов {money(res.pools.po_cand)};
                потенциал унификации (подтв.) {money(res.pools.unif)}; пул ЗИП {money(res.pools.pool)}; ставка стоимости владения {fmt(res.pools.holding_rate * 100, 'pct')}.
                Рычаги применяются последовательно к общим пулам, поэтому один и тот же запас не учитывается дважды. Межобщественное перемещение не считается экономией группы.
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
