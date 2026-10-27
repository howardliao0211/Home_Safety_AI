import AsyncStorage from "@react-native-async-storage/async-storage";
import type { AppState } from "../domain/model";
const key = "home-safety-preview-v1";
export const persistence = {
  async load(): Promise<AppState | null> {
    const raw = await AsyncStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  },
  async save(state: AppState) {
    await AsyncStorage.setItem(key, JSON.stringify(state));
  },
};
