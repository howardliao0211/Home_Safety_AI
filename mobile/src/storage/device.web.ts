import { IdentityStore } from "./identity-store";
const key = "home-safety-device-id-v1";
export function newApiId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
    "",
  );
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
const identity = new IdentityStore(
  async () => localStorage.getItem(key),
  async (id) => {
    localStorage.setItem(key, id);
  },
  newApiId,
);
export const getDeviceId = () => identity.get();
