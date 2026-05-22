import { useState, useEffect } from 'react'
import { View, Text, TextInput, TouchableOpacity, FlatList, StyleSheet, ActivityIndicator } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { getPlayers, addPlayer, removePlayer } from '../../utils/api'
import { F1_DARK, F1_CARD, F1_BORDER, F1_MUTED, F1_WHITE, F1_RED } from '../../constants/theme'

export default function PlayersScreen() {
  const [players, setPlayers] = useState<string[]>([])
  const [name,    setName]    = useState('')
  const [error,   setError]   = useState('')
  const [saving,  setSaving]  = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getPlayers()
      .then(setPlayers)
      .catch(() => setError('Failed to load players'))
      .finally(() => setLoading(false))
  }, [])

  async function handleAdd() {
    const trimmed = name.trim()
    if (!trimmed) return
    if (players.includes(trimmed)) { setError('Name already exists'); return }
    if (players.length >= 10)      { setError('Maximum 10 players');   return }
    setSaving(true)
    setError('')
    try {
      const updated = await addPlayer(trimmed)
      setPlayers(updated)
      setName('')
    } catch {
      setError('Failed to add player')
    } finally {
      setSaving(false)
    }
  }

  async function handleRemove(player: string) {
    try {
      const updated = await removePlayer(player)
      setPlayers(updated)
    } catch {
      setError('Failed to remove player')
    }
  }

  return (
    <SafeAreaView style={styles.safe} edges={['bottom']}>
      <View style={styles.content}>
        <Text style={styles.subtitle}>Add everyone competing in your group (max 10).</Text>

        <View style={styles.row}>
          <TextInput
            value={name}
            onChangeText={t => { setName(t); setError('') }}
            placeholder="Player name"
            placeholderTextColor={F1_MUTED}
            style={styles.input}
            onSubmitEditing={handleAdd}
            returnKeyType="done"
          />
          <TouchableOpacity
            onPress={handleAdd}
            disabled={saving}
            style={[styles.addBtn, saving && styles.addBtnDisabled]}
          >
            <Text style={styles.addBtnText}>{saving ? '…' : 'Add'}</Text>
          </TouchableOpacity>
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}

        {loading ? (
          <ActivityIndicator color={F1_RED} style={{ marginTop: 30 }} />
        ) : players.length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyText}>No players yet — add one above.</Text>
          </View>
        ) : (
          <FlatList
            data={players}
            keyExtractor={item => item}
            style={styles.list}
            renderItem={({ item, index }) => (
              <View style={styles.playerRow}>
                <Text style={styles.playerNum}>{index + 1}</Text>
                <Text style={styles.playerName}>{item}</Text>
                <TouchableOpacity onPress={() => handleRemove(item)}>
                  <Text style={styles.removeBtn}>Remove</Text>
                </TouchableOpacity>
              </View>
            )}
          />
        )}
      </View>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safe:      { flex: 1, backgroundColor: F1_DARK },
  content:   { flex: 1, padding: 16 },
  subtitle:  { color: F1_MUTED, fontSize: 13, marginBottom: 16 },
  row:       { flexDirection: 'row', gap: 8, marginBottom: 8 },
  input:     { flex: 1, backgroundColor: F1_CARD, borderWidth: 1, borderColor: F1_BORDER, borderRadius: 6, paddingHorizontal: 12, paddingVertical: 10, color: F1_WHITE, fontSize: 14 },
  addBtn:    { backgroundColor: F1_RED, borderRadius: 6, paddingHorizontal: 18, justifyContent: 'center' },
  addBtnDisabled: { opacity: 0.5 },
  addBtnText: { color: '#FFF', fontWeight: '700', fontSize: 14 },
  error:     { color: '#F87171', fontSize: 13, marginBottom: 8 },
  list:      { marginTop: 8 },
  empty:     { flex: 1, alignItems: 'center', justifyContent: 'center' },
  emptyText: { color: F1_MUTED },
  playerRow: { flexDirection: 'row', alignItems: 'center', backgroundColor: F1_CARD, borderWidth: 1, borderColor: F1_BORDER, borderRadius: 6, paddingHorizontal: 14, paddingVertical: 12, marginBottom: 6 },
  playerNum: { color: F1_MUTED, fontSize: 12, width: 24, textAlign: 'right', marginRight: 10 },
  playerName: { color: F1_WHITE, fontWeight: '600', fontSize: 15, flex: 1 },
  removeBtn: { color: F1_MUTED, fontSize: 13 },
})
