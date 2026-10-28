import { AuthScreen } from "@/auth/screen";
import { usePreview } from "@/hooks/preview-context";
import { router } from "expo-router";
export default function Account() {
  const { busy, refreshLatestAssessment } = usePreview();
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
