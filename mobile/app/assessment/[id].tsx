import { apiEnabled } from "@/api/config";
import { useState } from "react";
import { View } from "react-native";
import { Redirect, router, useLocalSearchParams } from "expo-router";
import { counts, ordered } from "@/domain/model";
import { usePreview } from "@/hooks/preview-context";
import { FindingCard } from "@/components/finding-card";
import { Icon } from "@/components/icon";
import {
  Button,
  ConfirmDialog,
  Copy,
  Disclaimer,
  Notice,
  Panel,
  PhotoView,
  PreviewNotice,
  Screen,
  styles,
} from "@/components/ui";
import { AssessmentSummary } from "@/components/suggestions";
import { AssessmentGate } from "@/components/assessment-gate";
import { NewAssessmentButton } from "@/components/new-assessment-button";
import { colors } from "@/components/theme";

export default function AssessmentRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return (
    <AssessmentGate id={id}>
      <AssessmentScreen />
    </AssessmentGate>
  );
}

function AssessmentScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { state, deleteAssessment } = usePreview();
  const [deleting, setDeleting] = useState(false);
  const assessment = state.assessments.find((a) => a.id === id);
  if (!assessment) return <Redirect href="/" />;
  if (assessment.status !== "complete")
    return <Redirect href={`/analysis/${id}`} />;
  const total = assessment.findings.length;
  const tally = counts(assessment.findings);
  return (
    <Screen>
      <View style={styles.row}>
        <Icon name="home" size={19} />
        <Copy kind="eyebrow">YOUR ROOM, ONE STEP AT A TIME</Copy>
      </View>
      <View style={{ gap: 12 }}>
        <Copy kind="title" accessibilityRole="header">
          {total
            ? "Your room checklist."
            : apiEnabled
              ? "No obvious visible hazards."
              : "Nothing obvious\nin this sample."}
        </Copy>
        <Copy style={{ color: colors.muted }}>
          {total
            ? `${total} potential concerns. Start with what matters most to your household.`
            : apiEnabled
              ? "No obvious visible hazards were identified. This is not a declaration that the room is safe."
              : "This sample returned no obvious visible hazards. It is not a declaration that the room is safe."}
        </Copy>
      </View>
      <PhotoView photo={assessment.photo} compact />
      <AssessmentSummary assessment={assessment} />
      <Copy kind="small">
        {new Date(assessment.createdAt).toLocaleDateString("en-AU", {
          day: "numeric",
          month: "long",
        })}{" "}
        ·{" "}
        {assessment.profiles.join(" · ") ||
          (assessment.householdContext
            ? "No groups selected"
            : "General assessment")}
      </Copy>
      <View style={{ gap: 4 }}>
        <Copy
          kind="eyebrow"
          accessibilityRole="header"
          style={{ textTransform: "uppercase" }}
        >
          Household details
        </Copy>
        <Copy
          style={
            assessment.householdContext ? undefined : { color: colors.muted }
          }
        >
          {assessment.householdContext || "No additional details"}
        </Copy>
      </View>
      <PreviewNotice />
      {total ? (
        <>
          <Panel style={{ backgroundColor: colors.soft, borderWidth: 0 }}>
            <View
              style={{
                ...styles.row,
                justifyContent: "space-between",
                flexWrap: "wrap",
              }}
            >
              <Copy kind="heading">Your checklist</Copy>
              <Copy style={{ fontWeight: "700" }}>
                {total - tally.open} of {total} handled
              </Copy>
            </View>
            <View
              accessibilityRole="progressbar"
              accessibilityLabel="Checklist items handled"
              aria-valuemin={0}
              aria-valuemax={total}
              aria-valuenow={total - tally.open}
              accessibilityValue={{
                min: 0,
                max: total,
                now: total - tally.open,
              }}
              style={{
                height: 6,
                borderRadius: 3,
                backgroundColor: "#c7d4c8",
                overflow: "hidden",
              }}
            >
              <View
                style={{
                  height: 6,
                  borderRadius: 3,
                  backgroundColor: colors.accent,
                  width: `${((total - tally.open) / total) * 100}%`,
                }}
              />
            </View>
            <Copy kind="small">
              {tally.open} open · {tally.resolved} resolved · {tally.dismissed}{" "}
              dismissed
            </Copy>
          </Panel>
          {tally.open === 0 && (
            <Notice title="You’ve reviewed every finding" tone="success">
              <Copy>
                {apiEnabled
                  ? "Your decisions are saved. These findings do not certify the room’s safety. You can reopen any item."
                  : "Your decisions are saved. This checklist covers only these sample findings and does not certify the room’s safety. You can reopen any item."}
              </Copy>
            </Notice>
          )}
          {ordered(assessment.findings).map((finding, index) => (
            <FindingCard
              key={finding.id}
              finding={finding}
              assessmentId={id}
              index={index}
            />
          ))}
        </>
      ) : (
        <Notice title="Keep looking out for your household">
          <Copy>
            A single photo can miss concerns outside the frame or hidden from
            view. Continue your usual checks and seek qualified help when
            needed.
          </Copy>
        </Notice>
      )}
      <NewAssessmentButton label="New assessment" secondary />
      <Disclaimer />
      <Button
        label="Delete assessment"
        icon="trash"
        variant="danger"
        onPress={() => setDeleting(true)}
      />
      <ConfirmDialog
        visible={deleting}
        title="Delete this assessment?"
        message={
          apiEnabled
            ? "Its checklist and all associated photos will be removed from the service and this device. This cannot be undone."
            : "Its checklist and all initial, follow-up, and review photos will be removed from this device. This cannot be undone."
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
