// Форматирование, API-клиент и типы. Расчётной логики здесь нет — все показатели приходят с сервера.

export type Unit = 'rub' | 'pct' | 'days' | 'months' | 'count' | 'num' | 'ratio' | 'index' | 'score' | 'qty'

export const nf = (v: number, d = 0) =>
  v.toLocaleString('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d })

export function money(v: number | null | undefined, d = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const a = Math.abs(v)
  const s = v < 0 ? '−' : ''
  if (a >= 1e9) return `${s}${nf(a / 1e9, d)} млрд ₽`
  if (a >= 1e6) return `${s}${nf(a / 1e6, d)} млн ₽`
  if (a >= 1e3) return `${s}${nf(a / 1e3, 0)} тыс. ₽`
  return `${s}${nf(a, 0)} ₽`
}

export function moneyShort(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const a = Math.abs(v)
  const s = v < 0 ? '−' : ''
  if (a >= 1e9) return `${s}${nf(a / 1e9, 1)} млрд`
  if (a >= 1e6) return `${s}${nf(a / 1e6, 0)} млн`
  if (a >= 1e3) return `${s}${nf(a / 1e3, 0)} тыс`
  return `${s}${nf(a, 0)}`
}

export function fmt(v: any, unit?: string, short = false): string {
  if (v === null || v === undefined || (typeof v === 'number' && Number.isNaN(v))) return unit === 'days' ? 'нет потребления' : '—'
  if (typeof v !== 'number') return String(v)
  switch (unit) {
    case 'rub': case 'money': return short ? moneyShort(v) : money(v)
    case 'pct': return `${nf(v, 1)}%`
    case 'days': return `${nf(v, 0)} дн.`
    case 'months': return `${nf(v, 1)} мес.`
    case 'count': case 'int': return nf(v, 0)
    case 'ratio': return nf(v, 2)
    case 'index': return nf(v, 1)
    case 'score': return nf(v, 2)
    default: return Math.abs(v) >= 100 ? nf(v, 0) : nf(v, Math.abs(v) < 10 ? 2 : 1)
  }
}

export type FilterState = {
  filters: Record<string, string[]>
  asof?: number
  window: string
  start?: number
  compare: string
  grain: string
  role: string
}

export function query(f: FilterState, extra: Record<string, any> = {}): string {
  const p = new URLSearchParams()
  Object.entries(f.filters).forEach(([k, v]) => { if (v && v.length) p.set(k, v.join(',')) })
  if (f.asof) p.set('asof', String(f.asof))
  p.set('window', f.window)
  if (f.window === 'custom' && f.start) p.set('start', String(f.start))
  p.set('compare', f.compare)
  p.set('grain', f.grain)
  p.set('role', f.role)
  Object.entries(extra).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') p.set(k, String(v)) })
  return p.toString()
}

export async function api<T = any>(path: string, f: FilterState | null, opts: { method?: string; body?: any; extra?: Record<string, any> } = {}): Promise<T> {
  const qs = f ? query(f, opts.extra) : new URLSearchParams(opts.extra || {}).toString()
  const url = `/api${path}${qs ? (path.includes('?') ? '&' : '?') + qs : ''}`
  const r = await fetch(url, {
    method: opts.method || 'GET',
    headers: { 'Content-Type': 'application/json', 'x-role': f?.role || 'board' },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  })
  if (!r.ok) {
    let msg = r.statusText
    try { msg = (await r.json()).detail || msg } catch { /* ignore */ }
    throw new Error(msg)
  }
  return r.json()
}

export const Q_TITLES: Record<string, string> = {
  what: '1. Что произошло?', where: '2. Где произошло?', why: '3. Почему?', risk: '4. Каковы риски и последствия?', action: '5. Что делать?',
}

export type Meta = any
