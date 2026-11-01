import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, type FilterState, type Meta } from './lib'

// Централизованная модель состояния: сквозные фильтры, период, роль, текущая витрина.
// Состояние синхронизируется с адресной строкой — представление можно передать ссылкой.

type Drill = { dim?: string; value?: string; label?: string; positionId?: string } | null

type Ctx = {
  meta: Meta | null
  f: FilterState
  setF: (u: Partial<FilterState>) => void
  setFilter: (k: string, v: string[]) => void
  page: string
  setPage: (p: string) => void
  drill: Drill
  setDrill: (d: Drill) => void
  assistantOpen: boolean
  setAssistantOpen: (b: boolean) => void
  version: number
  bump: () => void
  error: string | null
}

const C = createContext<Ctx>(null as any)
export const useApp = () => useContext(C)

const DEFAULT: FilterState = { filters: {}, window: '12', compare: 'prev', grain: 'month', role: 'board' }

function fromHash(): { f: FilterState; page: string } {
  try {
    const h = decodeURIComponent(location.hash.slice(1))
    if (!h) return { f: DEFAULT, page: 'v1' }
    const o = JSON.parse(h)
    return { f: { ...DEFAULT, ...o.f }, page: o.page || 'v1' }
  } catch {
    return { f: DEFAULT, page: 'v1' }
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const init = useMemo(fromHash, [])
  const [f, setFState] = useState<FilterState>(init.f)
  const [page, setPageState] = useState(init.page)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [drill, setDrill] = useState<Drill>(null)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [version, setVersion] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api('/meta', { ...DEFAULT, role: f.role }).then(m => { setMeta(m); setError(null) }).catch(e => setError(String(e.message || e)))
  }, [f.role, version])

  useEffect(() => {
    const h = encodeURIComponent(JSON.stringify({ f, page }))
    history.replaceState(null, '', '#' + h)
  }, [f, page])

  const setF = useCallback((u: Partial<FilterState>) => setFState(p => ({ ...p, ...u })), [])
  const setFilter = useCallback((k: string, v: string[]) => setFState(p => {
    const filters = { ...p.filters }
    if (v.length) filters[k] = v
    else delete filters[k]
    return { ...p, filters }
  }), [])
  const setPage = useCallback((p: string) => { setPageState(p); window.scrollTo(0, 0) }, [])
  const bump = useCallback(() => setVersion(v => v + 1), [])

  return (
    <C.Provider value={{ meta, f, setF, setFilter, page, setPage, drill, setDrill, assistantOpen, setAssistantOpen, version, bump, error }}>
      {children}
    </C.Provider>
  )
}

export function useApi<T = any>(path: string | null, extra: Record<string, any> = {}, deps: any[] = []) {
  const { f, version } = useApp()
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const key = JSON.stringify([path, f, extra, version, ...deps])
  useEffect(() => {
    if (!path) return
    let alive = true
    setLoading(true)
    setErr(null)
    api<T>(path, f, { extra }).then(d => { if (alive) { setData(d); setLoading(false) } })
      .catch(e => { if (alive) { setErr(String(e.message || e)); setLoading(false) } })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return { data, loading, err, setData }
}
