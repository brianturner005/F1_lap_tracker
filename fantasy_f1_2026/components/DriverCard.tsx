import { View, Text, StyleSheet } from 'react-native'
import { DRIVERS, TEAM_COLORS } from '../data/drivers'
import { F1_CARD, F1_BORDER, F1_MUTED, F1_WHITE } from '../constants/theme'

interface Props {
  id: string
  position: number
  drag: () => void
  isActive: boolean
}

export default function DriverCard({ id, position, drag, isActive }: Props) {
  const driver = DRIVERS.find(d => d.id === id)
  const teamColor = TEAM_COLORS[driver?.team ?? ''] ?? F1_MUTED

  return (
    <View style={[styles.card, isActive && styles.cardActive]}>
      <Text style={styles.pos}>{position}</Text>
      <View style={[styles.teamBar, { backgroundColor: teamColor }]} />
      <View style={styles.info}>
        <Text style={styles.name}>{driver?.name ?? id}</Text>
        <Text style={styles.team}>{driver?.team}</Text>
      </View>
      <Text style={[styles.abbr, { color: teamColor }]}>{driver?.abbr}</Text>
      <Text style={styles.handle} onLongPress={drag}>⠿</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: F1_CARD,
    borderWidth: 1,
    borderColor: F1_BORDER,
    borderRadius: 6,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginBottom: 6,
    gap: 10,
  },
  cardActive: {
    borderColor: '#4B5563',
    opacity: 0.85,
    elevation: 8,
    shadowColor: '#000',
    shadowOpacity: 0.4,
    shadowRadius: 6,
  },
  pos: {
    color: F1_MUTED,
    fontSize: 12,
    width: 22,
    textAlign: 'right',
  },
  teamBar: {
    width: 3,
    height: 28,
    borderRadius: 2,
  },
  info: {
    flex: 1,
  },
  name: {
    color: F1_WHITE,
    fontSize: 14,
    fontWeight: '600',
  },
  team: {
    color: F1_MUTED,
    fontSize: 11,
    marginTop: 1,
  },
  abbr: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1,
  },
  handle: {
    color: F1_MUTED,
    fontSize: 18,
    paddingLeft: 4,
  },
})
