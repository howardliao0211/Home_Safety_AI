import { apiEnabled } from "@/api/config";
export const firebaseConfig = {
  apiKey: process.env.EXPO_PUBLIC_FIREBASE_API_KEY || "local-emulator-key",
  projectId: process.env.EXPO_PUBLIC_FIREBASE_PROJECT_ID || "home-safety-local",
  authDomain: process.env.EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN,
  appId: process.env.EXPO_PUBLIC_FIREBASE_APP_ID || "home-safety-local",
};
export const emulatorUrl = process.env.EXPO_PUBLIC_AUTH_EMULATOR_URL;
if (apiEnabled && !__DEV__ && emulatorUrl)
  throw new Error("Auth emulator is forbidden in production builds.");
if (apiEnabled && !__DEV__ && firebaseConfig.projectId === "home-safety-local")
  throw new Error("Configure Firebase before building for production.");
