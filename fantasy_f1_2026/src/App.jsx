import { useState, useEffect } from 'react'
import { getPlayers } from './utils/api'
import Header from './components/Header'
import PlayerManager from './components/PlayerManager'
import PickEntry from './components/PickEntry'
import AdminResult from './components/AdminResult'
import Leaderboard from './components/Leaderboard'

export default function App() {
  const [activeTab, setActiveTab] = useState('picks')
  const [players, setPlayers] = useState([])

  useEffect(() => {
    getPlayers().then(setPlayers).catch(() => {})
  }, [])

  return (
    <div className="min-h-screen bg-f1dark">
      <Header activeTab={activeTab} setActiveTab={setActiveTab} />
      <main>
        {activeTab === 'picks'       && <PickEntry players={players} />}
        {activeTab === 'admin'       && <AdminResult />}
        {activeTab === 'leaderboard' && <Leaderboard players={players} />}
        {activeTab === 'players'     && <PlayerManager players={players} setPlayers={setPlayers} />}
      </main>
    </div>
  )
}
