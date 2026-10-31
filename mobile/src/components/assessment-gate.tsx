import { useEffect, useState, type ReactNode } from "react";
import { ActivityIndicator } from "react-native";
import { router } from "expo-router";
import { usePreview } from "@/hooks/preview-context";
import { Button, Copy, Screen } from "./ui";
import { colors } from "./theme";

/** Hydrate an assessment route opened without a local cache (including web reloads). */
export function AssessmentGate({
  id,
  children,
}: {
  id: string;
  children: ReactNode;
}) {
  const { state, loadAssessment } = usePreview();
  const exists = state.assessments.some((a) => a.id === id);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    if (!exists) {
      setFailed(false);
      void loadAssessment(id).then((result) => {
        if (active && !result) setFailed(true);
      });
    }
    return () => {
      active = false;
    };
  }, [id, exists, attempt]);
  if (exists) return <>{children}</>;
  return (
    <Screen>
      <Copy kind="heading">
        {failed ? "Assessment unavailable" : "Opening your assessment…"}
      </Copy>
      {failed ? (
        <>
          <Copy>
            We could not open this assessment. It may have been deleted, or your
            connection may be unavailable.
          </Copy>
          <Button
            label="Retry opening assessment"
            onPress={() => setAttempt((n) => n + 1)}
          />
        </>
      ) : (
        <ActivityIndicator color={colors.accent} />
      )}
      <Button
        label="Back to Home"
        variant="secondary"
        onPress={() => router.dismissTo("/")}
      />
    </Screen>
  );
}
