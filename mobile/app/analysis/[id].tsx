import { apiEnabled } from "@/api/config";
import { useEffect, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { Redirect, useLocalSearchParams, router } from "expo-router";
import { usePreview } from "@/hooks/preview-context";
import {
  Button,
  ConfirmDialog,
  Copy,
  Disclaimer,
  Notice,
  PhotoView,
  PreviewNotice,
  Screen,
  Step,
} from "@/components/ui";
import { useIsFocused } from "expo-router/react-navigation";
import { AssessmentGate } from "@/components/assessment-gate";
import { NewAssessmentButton } from "@/components/new-assessment-button";
import { colors } from "@/components/theme";

export default function AnalysisRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return (
    <AssessmentGate id={id}>
      <AnalysisScreen />
    </AssessmentGate>
  );
}

function AnalysisScreen() {
  const focused = useIsFocused();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { state, busy, runAnalysis, deleteAssessment } = usePreview();
  const [deleting, setDeleting] = useState(false);
  const assessment = state.assessments.find((a) => a.id === id);
  useEffect(() => {
    if (assessment?.status === "ready") void runAnalysis(id);
  }, [id, assessment?.status]);
  useEffect(() => {
    if (focused && assessment?.status === "complete") {
      router.replace(`/assessment/${id}`);
    }
  }, [id, assessment?.status, focused]);
  if (!assessment) return <Redirect href="/" />;
  if (assessment.status === "complete") return null;
  const failed =
    assessment.status === "failed" ||
    (assessment.status === "running" && !busy);
  return (
    <Screen>
      <Step
        number={3}
        label={apiEnabled ? "Room assessment" : "Sample assessment"}
      />
      <Copy kind="title" accessibilityRole="header">
        {failed
          ? "Let’s try that again."
          : apiEnabled
            ? "Reviewing your room."
            : "Preparing your sample checklist."}
      </Copy>
      <PhotoView photo={assessment.photo} />
      {failed ? (
        <Notice
          title={
            apiEnabled
              ? "The analysis could not finish"
              : "The preview could not finish"
          }
          tone="error"
        >
          <Copy>
            {assessment.error ||
              "The result could not be saved. Your input is still here."}
          </Copy>
          <Button
            label="Retry analysis"
            icon="refresh"
            onPress={() => void runAnalysis(id)}
          />
        </Notice>
      ) : (
        <View
          style={{ paddingVertical: 20, gap: 18, alignItems: "flex-start" }}
        >
          <ActivityIndicator color={colors.accent} size="large" />
          <Copy accessibilityLiveRegion="polite">
            {apiEnabled
              ? "Analysing visible information in your room photo. Your input is saved if you need to retry."
              : "Loading a predefined example. Your photo is not sent anywhere."}
          </Copy>
        </View>
      )}
      {failed && (
        <>
          <NewAssessmentButton label="Start another assessment" secondary />
          <Button
            label="Delete assessment"
            variant="danger"
            onPress={() => setDeleting(true)}
          />
        </>
      )}
      <PreviewNotice />
      <Disclaimer />
      <ConfirmDialog
        visible={deleting}
        title="Delete this assessment?"
        message={
          apiEnabled
            ? "This assessment and its photos will be removed from the service and this device."
            : "This failed assessment and its retained photo will be removed from this device."
        }
        confirm="Delete assessment and photos"
        onCancel={() => setDeleting(false)}
        onConfirm={() =>
          void deleteAssessment(id).then((ok) => {
            if (ok) {
              setDeleting(false);
              router.dismissAll();
              router.replace("/");
            }
          })
        }
      />
    </Screen>
  );
}
