export const apiEnabled = process.env.EXPO_PUBLIC_DATA_SOURCE !== "preview";
export const apiConfig = {
  baseUrl: (process.env.EXPO_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(
    /\/+$/,
    "",
  ),
  demoToken: process.env.EXPO_PUBLIC_DEMO_TOKEN || "",
};
export const stateKey = apiEnabled
  ? `state-api-v1:${apiConfig.baseUrl}`
  : "state";
