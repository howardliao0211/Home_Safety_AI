import AsyncStorage from "@react-native-async-storage/async-storage";
import type { AppState } from "../domain/model";
export function createPersistence(scope: string) {
  const key =
    scope === "preview" ? "home-safety-preview-v1" : `home-safety-${scope}`;
  return {
    async removeLegacy() {
      const keys = await AsyncStorage.getAllKeys();
      await AsyncStorage.multiRemove(
        keys.filter((key) => key.startsWith("home-safety-state-api-v1:")),
      );
    },
    async load(): Promise<AppState | null> {
      const raw = await AsyncStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    },
    async save(state: AppState) {
      await AsyncStorage.setItem(key, JSON.stringify(state));
    },
    async clear() {
      await AsyncStorage.removeItem(key);
    },
  };
}
