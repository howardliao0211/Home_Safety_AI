import { apiEnabled } from "@/api/config";
import { AuthScreen } from "@/auth/screen";
import { Redirect } from "expo-router";
export default function Account() {
  if (!apiEnabled) return <Redirect href="/" />;
  return <AuthScreen account />;
}
