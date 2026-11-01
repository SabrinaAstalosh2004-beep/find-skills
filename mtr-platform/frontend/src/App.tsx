import { useState } from 'react'
import { AppProvider, useApp } from './state'
import { AssistantPanel, Sidebar, TopBar } from './components/Layout'
import { DrillModal, ErrorBox, Spinner } from './components/ui'
import { VitrinePage } from './pages/VitrinePage'
import { ScenarioPage } from './pages/ScenarioPage'
import { DecisionCenter } from './pages/DecisionCenter'
import { Methodology, SliceBuilder, Sources } from './pages/Tools'

function Body() {
  const { meta, page, error } = useApp()
  if (error) return <div className="p-6"><ErrorBox msg={`Нет связи с сервером аналитики (${error}). Запустите backend: uvicorn app.main:app --port 8000`} /></div>
  if (!meta) return <Spinner label="Загрузка модели данных…" />
  if (page === 'v19') return <ScenarioPage />
  if (page === 'v20') return <DecisionCenter />
  if (page === 'slice') return <SliceBuilder />
  if (page === 'method') return <Methodology />
  if (page === 'sources') return <Sources />
  const vid = Number(page.replace('v', '')) || 1
  return <VitrinePage vid={vid} />
}

function Shell() {
  const [menu, setMenu] = useState(false)
  return (
    <div className="flex h-full">
      <Sidebar open={menu} onClose={() => setMenu(false)} />
      {menu && <div className="fixed inset-0 z-30 bg-slate-900/40 lg:hidden" onClick={() => setMenu(false)} />}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenu={() => setMenu(true)} />
        <main className="flex-1 overflow-x-hidden p-3 md:p-4"><Body /></main>
      </div>
      <DrillModal />
      <AssistantPanel />
    </div>
  )
}

export default function App() {
  return <AppProvider><Shell /></AppProvider>
}
