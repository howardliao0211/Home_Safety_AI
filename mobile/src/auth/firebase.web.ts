import { initializeApp, getApps } from "firebase/app";
import {
  initializeAuth,
  browserSessionPersistence,
  connectAuthEmulator,
  setPersistence,
} from "firebase/auth";
import { firebaseConfig, emulatorUrl } from "./config";
export const auth = initializeAuth(
  getApps()[0] ?? initializeApp(firebaseConfig),
  { persistence: browserSessionPersistence },
);
if (emulatorUrl)
  connectAuthEmulator(auth, emulatorUrl, { disableWarnings: true });
// A deletion receipt has no assessment authority; retain across reloads in this tab.
export const receiptStorage = {
  getItem: async (key: string) => sessionStorage.getItem(key),
  setItem: async (key: string, value: string) => {
    sessionStorage.setItem(key, value);
  },
  removeItem: async (key: string) => {
    sessionStorage.removeItem(key);
  },
};

export async function checkSessionPersistence() {
  const key = "firebase-persistence-preflight";
  sessionStorage.setItem(key, "ready");
  if (sessionStorage.getItem(key) !== "ready")
    throw new Error("Account storage is unavailable.");
  sessionStorage.removeItem(key);
  await setPersistence(auth, browserSessionPersistence);
}
