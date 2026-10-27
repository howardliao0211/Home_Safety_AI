import { apiEnabled } from "@/api/config";
import { useState } from "react";
import { TextInput, View } from "react-native";
import { Redirect, router, useLocalSearchParams } from "expo-router";
import { usePreview } from "@/hooks/preview-context";
import { Severity } from "@/components/finding-card";
import {
  Button,
  Copy,
  Disclaimer,
  Notice,
  Panel,
  PhotoView,
  PreviewNotice,
  Screen,
  Section,
  styles,
} from "@/components/ui";
import { colors } from "@/components/theme";

export default function FindingScreen() {
  const { assessmentId, findingId } = useLocalSearchParams<{
    assessmentId: string;
    findingId: string;
  }>();
  const { state, changeStatus, skip } = usePreview();
  const assessment = state.assessments.find((a) => a.id === assessmentId);
  const finding = assessment?.findings.find((f) => f.id === findingId);
  const [dismissing, setDismissing] = useState(false);
  const [note, setNote] = useState(finding?.note || "");
  if (!assessment || !finding) return <Redirect href="/" />;
  const pendingFollowUp = finding.submissions.some(
    (s) => s.kind === "follow-up" && s.status !== "complete",
  );
  return (
    <Screen>
      <Severity severity={finding.severity} />
      <View style={{ gap: 10 }}>
        <Copy kind="title" accessibilityRole="header">
          {finding.title}
        </Copy>
        <Copy kind="small">
          {finding.category} ·{" "}
          {finding.status === "open"
            ? "Open"
            : finding.status === "resolved"
              ? "Resolved by you"
              : "Dismissed by you"}
        </Copy>
      </View>
      <PhotoView photo={assessment.photo} compact />
      <PreviewNotice />
      <Section
        title={apiEnabled ? "Visible evidence" : "What the sample describes"}
      >
        <Copy>{finding.evidence}</Copy>
      </Section>
      <Section title="A practical next step">
        <Copy>{finding.recommendation}</Copy>
      </Section>
      <Notice title="What we can’t tell from a photo">
        <Copy>{finding.uncertainty}</Copy>
      </Notice>
      {finding.followUp && (
        <Panel>
          <Copy kind="eyebrow">A CLOSER LOOK</Copy>
          <Copy>{finding.followUp.question}</Copy>
          {finding.followUp.state === "available" ? (
            <>
              <Button
                label={
                  pendingFollowUp
                    ? "Continue follow-up"
                    : finding.followUp.kind === "photo"
                      ? "Add a close-up photo"
                      : "Answer a question"
                }
                icon={finding.followUp.kind === "photo" ? "camera" : "arrow"}
                variant="secondary"
                onPress={() =>
                  router.push({
                    pathname: "/evidence/[assessmentId]/[findingId]",
                    params: { assessmentId, findingId, kind: "follow-up" },
                  })
                }
              />
              {!pendingFollowUp && (
                <Button
                  label="Skip for now"
                  variant="text"
                  onPress={() => void skip(assessmentId, findingId)}
                />
              )}
            </>
          ) : (
            <Copy kind="small">
              {finding.followUp.state === "skipped"
                ? "You skipped this request. Uncertainty remains; you can still request a photo review."
                : apiEnabled
                  ? "Follow-up received. The finding was updated; you decide its status."
                  : "Follow-up received. The sample finding was updated; you decide its status."}
            </Copy>
          )}
        </Panel>
      )}
      {finding.submissions
        .filter((s) => s.status === "complete")
        .map((s) => (
          <Panel key={s.id}>
            <Copy kind="eyebrow">
              {s.kind === "review"
                ? apiEnabled
                  ? "AI PHOTO REVIEW"
                  : "SIMULATED PHOTO REVIEW"
                : apiEnabled
                  ? "AI FOLLOW-UP UPDATE"
                  : "SIMULATED FOLLOW-UP UPDATE"}
            </Copy>
            {s.photo && <PhotoView photo={s.photo} compact />}
            {!!s.text && (
              <>
                <Copy kind="small">Your answer</Copy>
                <Copy>{s.text}</Copy>
              </>
            )}
            <Copy>{s.feedback}</Copy>
          </Panel>
        ))}
      <Section title="You make the final call">
        <Copy kind="small">
          A photo check can add context. Only you decide when a finding is
          resolved.
        </Copy>
        <Button
          label={finding.status === "open" ? "Mark resolved" : "Reopen finding"}
          icon={finding.status === "open" ? "check" : "refresh"}
          onPress={() =>
            void changeStatus(
              assessmentId,
              findingId,
              finding.status === "open" ? "resolved" : "open",
            )
          }
        />
        <Button
          label="Ask AI to check"
          icon="camera"
          variant="secondary"
          onPress={() =>
            router.push({
              pathname: "/evidence/[assessmentId]/[findingId]",
              params: { assessmentId, findingId, kind: "review" },
            })
          }
        />
        <Copy kind="small">
          {apiEnabled
            ? "A review adds evidence; you decide whether to resolve the finding."
            : "Photo review is simulated in this preview."}
        </Copy>
        {finding.status === "open" && !dismissing && (
          <Button
            label="Dismiss as not relevant"
            variant="text"
            onPress={() => setDismissing(true)}
          />
        )}
        {dismissing && (
          <Panel>
            <Copy kind="heading">Why isn’t this relevant?</Copy>
            <Copy kind="small">
              Optional note. You can reopen this finding later.
            </Copy>
            <TextInput
              accessibilityLabel="Dismissal note (optional)"
              placeholder="Add a note for yourself"
              placeholderTextColor={colors.muted}
              multiline
              value={note}
              onChangeText={setNote}
              style={styles.input}
            />
            <Button
              label="Save dismissal"
              variant="secondary"
              onPress={() =>
                void changeStatus(
                  assessmentId,
                  findingId,
                  "dismissed",
                  note,
                ).then((ok) => {
                  if (ok) setDismissing(false);
                })
              }
            />
            <Button
              label="Cancel dismissal"
              variant="text"
              onPress={() => setDismissing(false)}
            />
          </Panel>
        )}
        {finding.status === "dismissed" && !!finding.note && (
          <Copy kind="small">Your note: {finding.note}</Copy>
        )}
        <Button
          label="Back to checklist"
          variant="text"
          onPress={() => router.dismissTo(`/assessment/${assessmentId}`)}
        />
      </Section>
      <Disclaimer />
    </Screen>
  );
}
