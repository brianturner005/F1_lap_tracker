import { useState } from 'react'
import { View, Text, TouchableOpacity, ScrollView, StyleSheet } from 'react-native'
import { RACES } from '../data/races'
import { DRIVERS } from '../data/drivers'
import { LeaderboardData } from '../utils/api'
import { F1_CARD, F1_BORDER, F1_MUTED, F1_WHITE, F1_RED, F1_DARK } from '../constants/theme'

const SCORING_GP     = { 0: 25, 1: 10, 2: 5, 3: 2 } as Record<number, number>
const SCORING_SPRINT = { 0: 10, 1: 4,  2: 2, 3: 1 } as Record<number, number>
const scoringTable = (raceId: string) => raceId.endsWith('_sprint') ? SCORING_SPRINT : SCORING_GP

function medal(rank: number) {
  if (rank === 1) return '🥇'
  if (rank === 2) return '🥈'
  if (rank === 3) return '🥉'
  return `${rank}.`
}

interface Props {
  rank: number
  player: string
  data: { total: number; races: Record<string, number> }
  leaderboard: LeaderboardData
}

export default function LeaderboardRow({ rank, player, data, leaderboard }: Props) {
  const [expandedRace, setExpandedRace] = useState<string | null>(null)

  const racesWithResults = RACES.filter(r => leaderboard.results[r.id])

  const breakdown = expandedRace ? (() => {
    const result = leaderboard.results[expandedRace]
    const picks  = leaderboard.picksByRace[expandedRace]?.[player]
    const table  = scoringTable(expandedRace)
    if (!result) return null
    return result.map((driverId, actualIdx) => {
      const driver       = DRIVERS.find(d => d.id === driverId)
      const predictedIdx = picks ? picks.indexOf(driverId) : -1
      const diff         = predictedIdx === -1 ? null : Math.abs(predictedIdx - actualIdx)
      const pts          = diff == null ? 0 : (table[diff] ?? 0)
      return { driver, predictedIdx, diff, pts }
    })
  })() : null

  return (
    <View style={styles.card}>
      {/* Header row */}
      <View style={styles.header}>
        <Text style={styles.medal}>{medal(rank)}</Text>
        <Text style={styles.player}>{player}</Text>
        <View style={styles.totalBox}>
          <Text style={styles.totalPts}>{data.total}</Text>
          <Text style={styles.ptsLabel}>pts</Text>
        </View>
      </View>

      {/* Race pills */}
      {racesWithResults.length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.pillRow} contentContainerStyle={styles.pillContent}>
          {racesWithResults.map(race => {
            const pts = data.races[race.id] ?? null
            const isExpanded = expandedRace === race.id
            return (
              <TouchableOpacity
                key={race.id}
                onPress={() => setExpandedRace(isExpanded ? null : race.id)}
                style={[styles.pill, isExpanded && styles.pillActive]}
              >
                <Text style={styles.pillFlag}>{race.country}</Text>
                {race.sprint && <Text style={styles.pillSprint}>S</Text>}
                <Text style={[styles.pillPts, pts != null && styles.pillPtsActive]}>
                  {pts != null ? `${pts}` : '–'}
                </Text>
              </TouchableOpacity>
            )
          })}
        </ScrollView>
      )}

      {/* Expanded breakdown */}
      {breakdown && (
        <View style={styles.breakdown}>
          <View style={styles.breakdownHeader}>
            <Text style={[styles.bCol, { flex: 0.4 }]}>Pos</Text>
            <Text style={[styles.bCol, { flex: 1.5 }]}>Driver</Text>
            <Text style={[styles.bCol, { flex: 0.8 }]}>Pick</Text>
            <Text style={[styles.bCol, { flex: 0.5, textAlign: 'right' }]}>Pts</Text>
          </View>
          {breakdown.map(({ driver, predictedIdx, diff, pts }, i) => (
            <View key={driver?.id ?? i} style={styles.breakdownRow}>
              <Text style={[styles.bCell, { flex: 0.4, color: F1_MUTED }]}>{i + 1}</Text>
              <Text style={[styles.bCell, { flex: 1.5 }]}>{driver?.name ?? '?'}</Text>
              <Text style={[styles.bCell, { flex: 0.8, color: F1_MUTED }]}>
                {predictedIdx === -1 ? '—' : `P${predictedIdx + 1}`}
                {diff === 0 ? ' ✓' : diff != null && diff > 0 ? ` ±${diff}` : ''}
              </Text>
              <Text style={[styles.bCell, { flex: 0.5, textAlign: 'right', color: pts > 0 ? F1_WHITE : F1_MUTED }]}>
                {pts > 0 ? `+${pts}` : '0'}
              </Text>
            </View>
          ))}
        </View>
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: F1_CARD,
    borderWidth: 1,
    borderColor: F1_BORDER,
    borderRadius: 8,
    overflow: 'hidden',
    marginBottom: 10,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 14,
    gap: 10,
  },
  medal:    { fontSize: 22, width: 32, textAlign: 'center' },
  player:   { color: F1_WHITE, fontWeight: '600', fontSize: 16, flex: 1 },
  totalBox: { alignItems: 'flex-end' },
  totalPts: { color: F1_WHITE, fontWeight: '700', fontSize: 20, lineHeight: 22 },
  ptsLabel: { color: F1_MUTED, fontSize: 11 },
  pillRow:  { backgroundColor: F1_DARK + '88', paddingVertical: 8 },
  pillContent: { paddingHorizontal: 12, gap: 6, flexDirection: 'row' },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: F1_CARD,
    borderWidth: 1,
    borderColor: F1_BORDER,
    borderRadius: 4,
    paddingHorizontal: 7,
    paddingVertical: 4,
  },
  pillActive:  { borderColor: F1_RED + '80', backgroundColor: F1_RED + '20' },
  pillFlag:    { fontSize: 13 },
  pillSprint:  { color: '#C084FC', fontSize: 11, fontWeight: '700' },
  pillPts:     { color: F1_MUTED, fontSize: 12 },
  pillPtsActive: { color: F1_WHITE, fontWeight: '600' },
  breakdown:   { borderTopWidth: 1, borderTopColor: F1_BORDER },
  breakdownHeader: {
    flexDirection: 'row',
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: F1_DARK + '55',
  },
  bCol:   { color: F1_MUTED, fontSize: 11, fontWeight: '500' },
  breakdownRow: {
    flexDirection: 'row',
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderTopWidth: 1,
    borderTopColor: F1_BORDER + '55',
  },
  bCell: { color: F1_WHITE, fontSize: 12 },
})
