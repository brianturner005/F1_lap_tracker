import { useState, useEffect } from 'react'
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from 'react-native'
import { Picker } from '@react-native-picker/picker'
import { SafeAreaView } from 'react-native-safe-area-context'
import { RACES } from '../../data/races'
import { DEFAULT_ORDER } from '../../data/drivers'
import { getResultForRace, saveResultForRace } from '../../utils/api'
import SortableList from '../../components/SortableList'
import { F1_DARK, F1_CARD, F1_BORDER, F1_MUTED, F1_WHITE, F1_RED } from '../../constants/theme'

export default function AdminScreen() {
  const [raceId,  setRaceId]  = useState(RACES[0].id)
  const [order,   setOrder]   = useState<string[]>([...DEFAULT_ORDER])
  const [loading, setLoading] = useState(false)
  const [saving,  setSaving]  = useState(false)
  const [message, setMessage] = useState<{ text: string; type: 'ok' | 'err' } | null>(null)

  useEffect(() => {
    setLoading(true)
    setMessage(null)
    getResultForRace(raceId)
      .then(result => setOrder(result ?? [...DEFAULT_ORDER]))
      .catch(() => setMessage({ text: 'Failed to load result', type: 'err' }))
      .finally(() => setLoading(false))
  }, [raceId])

  async function handleSave() {
    setSaving(true)
    setMessage(null)
    try {
      await saveResultForRace(raceId, order)
      setMessage({ text: 'Result saved — scores updated!', type: 'ok' })
      setTimeout(() => setMessage(null), 2500)
    } catch {
      setMessage({ text: 'Failed to save — check connection', type: 'err' })
    } finally {
      setSaving(false)
    }
  }

  const race = RACES.find(r => r.id === raceId)

  return (
    <SafeAreaView style={styles.safe} edges={['bottom']}>
      <View style={styles.top}>
        <View style={styles.adminBadge}>
          <Text style={styles.adminText}>ADMIN</Text>
        </View>
        <Text style={styles.subtitle}>Enter the official finishing order. Scores recalculate on save.</Text>
      </View>

      <View style={styles.pickerBox}>
        <Text style={styles.label}>RACE</Text>
        <View style={styles.pickerWrap}>
          <Picker selectedValue={raceId} onValueChange={setRaceId} style={styles.picker} dropdownIconColor={F1_MUTED}>
            {RACES.map(r => <Picker.Item key={r.id} label={`${r.country} ${r.name}`} value={r.id} color={F1_WHITE} />)}
          </Picker>
        </View>
      </View>

      {loading ? (
        <ActivityIndicator color={F1_RED} style={{ marginTop: 40 }} />
      ) : (
        <>
          <View style={styles.raceHeader}>
            <Text style={styles.raceLabel}>{race?.country} {race?.name?.toUpperCase()}</Text>
            {race?.sprint && (
              <View style={styles.sprintBadge}>
                <Text style={styles.sprintText}>SPRINT</Text>
              </View>
            )}
            <TouchableOpacity onPress={() => setOrder([...DEFAULT_ORDER])}>
              <Text style={styles.reset}>Reset</Text>
            </TouchableOpacity>
          </View>

          <View style={{ flex: 1, paddingHorizontal: 16 }}>
            <SortableList order={order} setOrder={setOrder} />
          </View>

          <View style={styles.footer}>
            <TouchableOpacity
              onPress={handleSave}
              disabled={saving}
              style={[styles.saveBtn, saving && styles.saveBtnDisabled]}
            >
              <Text style={styles.saveBtnText}>{saving ? 'Saving…' : 'Confirm Result'}</Text>
            </TouchableOpacity>
            {message && (
              <Text style={message.type === 'ok' ? styles.msgOk : styles.msgErr}>
                {message.text}
              </Text>
            )}
          </View>
        </>
      )}
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safe:        { flex: 1, backgroundColor: F1_DARK },
  top:         { padding: 16, gap: 6 },
  adminBadge:  { alignSelf: 'flex-start', backgroundColor: F1_RED + '25', borderWidth: 1, borderColor: F1_RED + '55', borderRadius: 4, paddingHorizontal: 8, paddingVertical: 3 },
  adminText:   { color: F1_RED, fontSize: 11, fontWeight: '700', letterSpacing: 1 },
  subtitle:    { color: F1_MUTED, fontSize: 13 },
  pickerBox:   { paddingHorizontal: 16, paddingBottom: 8 },
  label:       { color: F1_MUTED, fontSize: 11, letterSpacing: 1, marginBottom: 4 },
  pickerWrap:  { backgroundColor: F1_CARD, borderWidth: 1, borderColor: F1_BORDER, borderRadius: 6 },
  picker:      { color: F1_WHITE },
  raceHeader:  { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingBottom: 8, gap: 8 },
  raceLabel:   { color: F1_MUTED, fontSize: 11, letterSpacing: 0.5, flex: 1 },
  sprintBadge: { borderWidth: 1, borderColor: '#C084FC55', borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2 },
  sprintText:  { color: '#C084FC', fontSize: 10, fontWeight: '600' },
  reset:       { color: F1_MUTED, fontSize: 12 },
  footer:      { padding: 16, gap: 8 },
  saveBtn:     { backgroundColor: F1_RED, borderRadius: 8, paddingVertical: 14, alignItems: 'center' },
  saveBtnDisabled: { opacity: 0.5 },
  saveBtnText: { color: '#FFF', fontWeight: '700', fontSize: 15 },
  msgOk:       { color: '#4ADE80', textAlign: 'center', fontSize: 13 },
  msgErr:      { color: '#F87171', textAlign: 'center', fontSize: 13 },
})
