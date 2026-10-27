import AsyncStorage from "@react-native-async-storage/async-storage";
import { randomUUID } from "expo-crypto";
import { IdentityStore } from "./identity-store";
const key = "home-safety-device-id-v1";
export const newApiId = randomUUID;
const identity = new IdentityStore(
  () => AsyncStorage.getItem(key),
  (id) => AsyncStorage.setItem(key, id),
  newApiId,
);
export const getDeviceId = () => identity.get();
