import { apiEnabled } from "@/api/config";
import { AuthScreen } from "@/auth/screen";
import { usePreview } from "@/hooks/preview-context";
import { router, Redirect } from "expo-router";
export default function Account() {
  const { busy, refreshLatestAssessment } = usePreview();
  if (!apiEnabled) return <Redirect href="/" />;
  return (
    <AuthScreen
      account
      refreshDisabled={busy}
      onRefresh={async () => {
        if (!(await refreshLatestAssessment()))
          throw new Error("Could not refresh your assessment.");
        router.replace("/");
      }}
    />
  );
}
