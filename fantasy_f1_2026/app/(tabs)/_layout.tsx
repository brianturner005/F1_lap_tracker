import { Tabs } from 'expo-router'
import { F1_DARK, F1_CARD, F1_BORDER, F1_RED, F1_MUTED } from '../../constants/theme'

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerStyle:      { backgroundColor: F1_CARD, borderBottomColor: F1_BORDER, borderBottomWidth: 1 },
        headerTintColor:  '#FFFFFF',
        headerTitleStyle: { fontWeight: '700', letterSpacing: 1 },
        tabBarStyle:      { backgroundColor: F1_CARD, borderTopColor: F1_BORDER },
        tabBarActiveTintColor:   F1_RED,
        tabBarInactiveTintColor: F1_MUTED,
      }}
    >
      <Tabs.Screen
        name="index"
        options={{ title: 'Submit Pick', tabBarLabel: 'Picks', tabBarIcon: ({ color }) => <TabIcon emoji="🏁" color={color} /> }}
      />
      <Tabs.Screen
        name="leaderboard"
        options={{ title: 'Leaderboard', tabBarLabel: 'Standings', tabBarIcon: ({ color }) => <TabIcon emoji="🏆" color={color} /> }}
      />
      <Tabs.Screen
        name="admin"
        options={{ title: 'Enter Result', tabBarLabel: 'Admin', tabBarIcon: ({ color }) => <TabIcon emoji="🔧" color={color} /> }}
      />
      <Tabs.Screen
        name="players"
        options={{ title: 'Players', tabBarLabel: 'Players', tabBarIcon: ({ color }) => <TabIcon emoji="👥" color={color} /> }}
      />
    </Tabs>
  )
}

function TabIcon({ emoji, color }: { emoji: string; color: string }) {
  const { Text } = require('react-native')
  return <Text style={{ fontSize: 18, opacity: color === F1_RED ? 1 : 0.5 }}>{emoji}</Text>
}
