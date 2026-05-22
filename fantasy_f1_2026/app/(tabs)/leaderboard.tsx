import { useState, useEffect } from 'react'
import { View, Text, FlatList, StyleSheet, ActivityIndicator, TouchableOpacity } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { RACES } from '../../data/races'
import { getPlayers, getLeaderboard, LeaderboardData } from '../../utils/api'
import LeaderboardRow from '../../components/LeaderboardRow'
import { F1_DARK, F1_MUTED, F1_WHITE, F1_RED } from '../../constants/theme'

export default function LeaderboardScreen() {
  const [players,     setPlayers]     = useState<string[]>([])
  const [leaderboard, setLeaderboard] = useState<LeaderboardData | null>(null)
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      const [p, lb] = await Promise.all([getPlayers(), getLeaderboard()])
      setPlayers(p)
      setLeaderboard(lb)
    } catch {
      setError('Failed to load leaderboard')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const ranked = players
    .map(player => ({ player, data: leaderboard?.scores[player] ?? { total: 0, races: {} } }))
    .sort((a, b) => b.data.total - a.data.total)

  const racesComplete = leaderboard ? RACES.filter(r => leaderboard.results[r.id]).length : 0

  return (
    <SafeAreaView style={styles.safe} edges={['bottom']}>
      <View style={styles.meta}>
        <Text style={styles.metaText}>{racesComplete} / {RACES.length} events complete</Text>
        <TouchableOpacity onPress={load}>
          <Text style={styles.refresh}>Refresh</Text>
        </TouchableOpacity>
      </View>

      {loading ? (
        <ActivityIndicator color={F1_RED} style={{ marginTop: 40 }} />
      ) : error ? (
        <Text style={styles.error}>{error}</Text>
      ) : ranked.length === 0 ? (
        <View style={styles.empty}>
          <Text style={styles.emptyText}>Add players in the Players tab to see standings.</Text>
        </View>
      ) : (
        <FlatList
          data={ranked}
          keyExtractor={item => item.player}
          contentContainerStyle={styles.list}
          renderItem={({ item, index }) => (
            <LeaderboardRow
              rank={index + 1}
              player={item.player}
              data={item.data}
              leaderboard={leaderboard!}
            />
          )}
        />
      )}
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safe:      { flex: 1, backgroundColor: F1_DARK },
  meta:      { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 10 },
  metaText:  { color: F1_MUTED, fontSize: 12 },
  refresh:   { color: F1_RED, fontSize: 13, fontWeight: '600' },
  list:      { padding: 16 },
  empty:     { flex: 1, alignItems: 'center', justifyContent: 'center' },
  emptyText: { color: F1_MUTED, textAlign: 'center' },
  error:     { color: '#F87171', textAlign: 'center', marginTop: 40 },
})
