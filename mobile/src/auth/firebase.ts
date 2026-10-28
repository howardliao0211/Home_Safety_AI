import { initializeApp, getApps } from "firebase/app";
import * as sdk from "firebase/auth";
import * as SecureStore from "expo-secure-store";
import { randomUUID } from "expo-crypto";
import { secureStorage, type SecretStorage } from "./secure-storage";
import { firebaseConfig, emulatorUrl } from "./config";
const encrypted = secureStorage(
  {
    getItem: (key) => SecureStore.getItemAsync(key),
    setItem: (key, value) =>
      SecureStore.setItemAsync(key, value, {
        keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
      }),
    removeItem: (key) => SecureStore.deleteItemAsync(key),
  },
  randomUUID,
);
const native = sdk as typeof sdk & {
  getReactNativePersistence: (storage: SecretStorage) => sdk.Persistence;
};
const persistence = native.getReactNativePersistence(encrypted);
export const auth = sdk.initializeAuth(
  getApps()[0] ?? initializeApp(firebaseConfig),
  { persistence },
);
if (emulatorUrl)
  sdk.connectAuthEmulator(auth, emulatorUrl, { disableWarnings: true });
export const receiptStorage = encrypted;

export async function checkSessionPersistence() {
  if (!(await SecureStore.isAvailableAsync()))
    throw new Error("Secure account storage is unavailable on this device.");
  const key = "firebase-persistence-preflight";
  await encrypted.setItem(key, "ready");
  if ((await encrypted.getItem(key)) !== "ready")
    throw new Error("Secure account storage could not be verified.");
  await encrypted.removeItem(key);
  await sdk.setPersistence(auth, persistence);
}
