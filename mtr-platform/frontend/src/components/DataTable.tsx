import { useMemo, useState } from 'react'
import { flexRender, getCoreRowModel, getFilteredRowModel, getPaginationRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState } from '@tanstack/react-table'
import { fmt } from '../lib'

const STATUS_COLORS: Record<string, string> = {
  'Перенесён': 'bg-amber-100 text-amber-800', 'Отменён': 'bg-red-100 text-red-700', 'Завершён': 'bg-slate-100 text-slate-600',
  'В графике': 'bg-blue-50 text-blue-700', 'Нет потребления': 'bg-slate-100 text-slate-600', 'Рассчитано': 'bg-emerald-50 text-emerald-700',
  'Риск отсутствия ЗИП': 'bg-red-100 text-red-700', 'Избыток с учётом надёжности': 'bg-amber-100 text-amber-800', 'Норма': 'bg-emerald-50 text-emerald-700',
  'Да': 'bg-red-100 text-red-700', 'Нет': 'bg-slate-100 text-slate-600', 'Лучший': 'bg-emerald-100 text-emerald-800',
  'Изменено техническое решение': 'bg-violet-100 text-violet-700',
}

export type TableSpec = { columns: { key: string; label: string; type: string }[]; rows: any[]; drill?: { dim?: string; key?: string } | null; n_total?: number; total?: Record<string, number>; row_key?: string }

export function cell(v: any, type: string) {
  if (type === 'money') return fmt(v, 'rub')
  if (type === 'pct') return v == null ? '—' : fmt(v, 'pct')
  if (type === 'days') return v == null ? <span className="text-slate-400">нет потребл.</span> : fmt(v, 'days')
  if (type === 'int') return v == null ? '—' : fmt(v, 'int')
  if (type === 'num') return v == null ? '—' : fmt(v, 'num')
  if (type === 'date') return v ? String(v).slice(0, 10) : '—'
  if (type === 'status') return v == null || v === '' ? '' : <span className={`chip ${STATUS_COLORS[String(v)] || 'bg-slate-100 text-slate-700'}`}>{String(v)}</span>
  if (typeof v === 'boolean') return v ? 'Да' : 'Нет'
  return v == null ? '—' : String(v)
}

export function DataTable({ spec, onRow, onDecision, pageSize = 25, compact = false }: {
  spec: TableSpec; onRow?: (row: any) => void; onDecision?: (row: any, decision: string) => void; pageSize?: number; compact?: boolean
}) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [q, setQ] = useState('')
  const cols = useMemo<ColumnDef<any>[]>(() => spec.columns.map(c => ({
    id: c.key, accessorFn: (r: any) => r[c.key], header: c.label,
    cell: info => c.type === 'decision' && onDecision ? (
      <select className="sel" value={info.getValue() as string} onClick={e => e.stopPropagation()} onChange={e => onDecision(info.row.original, e.target.value)}>
        <option disabled>Не рассмотрено</option><option>Принято в работу</option><option>На технической проверке</option><option>Отклонено</option>
        {!['Не рассмотрено', 'Принято в работу', 'На технической проверке', 'Отклонено'].includes(info.getValue() as string) && <option>{info.getValue() as string}</option>}
      </select>) : cell(info.getValue(), c.type),
    meta: c.type,
    sortingFn: ['money', 'pct', 'num', 'int', 'days'].includes(c.type) ? 'basic' : 'alphanumeric',
    sortUndefined: 'last',
  })), [spec, onDecision])
  const table = useReactTable({
    data: spec.rows, columns: cols, state: { sorting, globalFilter: q }, onSortingChange: setSorting, onGlobalFilterChange: setQ,
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(), initialState: { pagination: { pageSize } },
  })
  const num = (t: string) => ['money', 'pct', 'num', 'int', 'days'].includes(t)
  const pages = table.getPageCount()
  return (
    <div className="text-xs">
      {spec.rows.length > 8 && (
        <div className="mb-2 flex items-center justify-between gap-2">
          <input className="sel w-56" placeholder="Поиск в таблице…" value={q} onChange={e => setQ(e.target.value)} />
          <span className="text-slate-500">Строк: {table.getFilteredRowModel().rows.length}{spec.n_total && spec.n_total > spec.rows.length ? ` (показано ${spec.rows.length} из ${spec.n_total})` : ''}</span>
        </div>
      )}
      <div className="overflow-x-auto scroll-thin">
        <table className="w-full border-collapse">
          <thead>
            {table.getHeaderGroups().map(hg => (
              <tr key={hg.id} className="border-b border-slate-200 bg-slate-50">
                {hg.headers.map(h => {
                  const t = (h.column.columnDef.meta as string) || 'text'
                  const s = h.column.getIsSorted()
                  return (
                    <th key={h.id} onClick={h.column.getToggleSortingHandler()} className={`cursor-pointer select-none whitespace-nowrap px-2 py-1.5 font-semibold text-slate-600 ${num(t) ? 'text-right' : 'text-left'}`}>
                      {flexRender(h.column.columnDef.header, h.getContext())}{s === 'asc' ? ' ▲' : s === 'desc' ? ' ▼' : ''}
                    </th>)
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map(r => (
              <tr key={r.id} onClick={onRow ? () => onRow(r.original) : undefined} className={`border-b border-slate-100 ${onRow ? 'cursor-pointer hover:bg-blue-50/60' : 'hover:bg-slate-50'}`}>
                {r.getVisibleCells().map(c => {
                  const t = (c.column.columnDef.meta as string) || 'text'
                  return <td key={c.id} className={`px-2 ${compact ? 'py-0.5' : 'py-1'} ${num(t) ? 'text-right tabular-nums whitespace-nowrap' : 'max-w-[340px]'}`}>{flexRender(c.column.columnDef.cell, c.getContext())}</td>
                })}
              </tr>
            ))}
            {spec.total && Object.keys(spec.total).length > 0 && (
              <tr className="border-t-2 border-slate-300 bg-slate-50 font-semibold">
                {spec.columns.map((c, i) => <td key={c.key} className={`px-2 py-1 ${num(c.type) ? 'text-right tabular-nums' : ''}`}>{i === 0 ? 'Итого' : (c.key in spec.total! ? cell(spec.total![c.key], c.type) : '')}</td>)}
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="mt-2 flex items-center gap-2 text-slate-600">
          <button className="btn" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>‹</button>
          <span>Стр. {table.getState().pagination.pageIndex + 1} из {pages}</span>
          <button className="btn" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>›</button>
        </div>
      )}
    </div>
  )
}
