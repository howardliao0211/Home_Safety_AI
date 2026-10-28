export const apiEnabled = process.env.EXPO_PUBLIC_DATA_SOURCE !== "preview";
export const apiConfig = {
  baseUrl: (process.env.EXPO_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(
    /\/+$/,
    "",
  ),
};
export const stateKey = apiEnabled
  ? `state-api-v1:${apiConfig.baseUrl}`
  : "state";

export function accountScope(project: string, uid: string) {
  return `account-v2:${encodeURIComponent(project)}:${encodeURIComponent(apiConfig.baseUrl)}:${encodeURIComponent(uid)}`;
}
