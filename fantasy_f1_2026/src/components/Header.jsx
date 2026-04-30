export default function Header({ activeTab, setActiveTab }) {
  const tabs = [
    { id: 'picks',       label: 'Submit Pick'   },
    { id: 'admin',       label: 'Enter Result'  },
    { id: 'leaderboard', label: 'Leaderboard'   },
    { id: 'players',     label: 'Players'       },
  ]

  return (
    <header className="border-b border-f1border">
      <div className="max-w-5xl mx-auto px-4">
        <div className="flex items-center gap-3 py-4">
          <div className="w-1 h-8 bg-f1red rounded-full" />
          <div>
            <h1 className="text-xl font-bold tracking-wider text-white leading-none">
              FANTASY F1
            </h1>
            <p className="text-xs text-f1muted tracking-widest">2026 SEASON</p>
          </div>
        </div>
        <nav className="flex gap-1 -mb-px">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2.5 text-sm font-medium tracking-wide border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-f1red text-white'
                  : 'border-transparent text-f1muted hover:text-white'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>
    </header>
  )
}
