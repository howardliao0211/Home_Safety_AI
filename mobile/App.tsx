import { StatusBar } from 'expo-status-bar';
import { StyleSheet, Text, View } from 'react-native';

export default function App() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Home Safety AI</Text>
      <Text style={styles.description}>
        Your frontend development environment is ready.
      </Text>
      <Text style={styles.hint}>Edit mobile/App.tsx to start building.</Text>
      <Text style={styles.disclaimer}>
        AI-generated suggestions based on visible information only; not a
        professional home safety inspection.
      </Text>
      <StatusBar style="dark" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f8f7',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 28,
  },
  title: { fontSize: 32, fontWeight: '700', color: '#183f36' },
  description: { marginTop: 20, fontSize: 18, textAlign: 'center' },
  hint: { marginTop: 12, fontSize: 14, color: '#4b635c', textAlign: 'center' },
  disclaimer: {
    marginTop: 40,
    maxWidth: 420,
    fontSize: 12,
    lineHeight: 18,
    color: '#4b635c',
    textAlign: 'center',
  },
});
