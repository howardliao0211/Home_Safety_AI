import { FindingHighlight } from "@/components/finding-highlight";
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
  const { state, changeStatus } = usePreview();
  const assessment = state.assessments.find((a) => a.id === assessmentId);
  const finding = assessment?.findings.find((f) => f.id === findingId);
  const [dismissing, setDismissing] = useState(false);
  const [note, setNote] = useState(finding?.note || "");
  if (!assessment || !finding) return <Redirect href="/" />;
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
      <FindingHighlight
        key={`${finding.id}-${finding.contentRevision}`}
        assessment={assessment}
        finding={finding}
      />
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
      <Panel>
        <Copy kind="heading">Questions about this finding?</Copy>
        <Copy>
          Chat offers guidance. You decide what to do and when to change its
          status.
        </Copy>
        <Button
          label="Chat about it"
          variant="secondary"
          icon="arrow"
          onPress={() =>
            router.push({
              pathname: "/chat/[assessmentId]/[findingId]",
              params: { assessmentId, findingId },
            })
          }
        />
      </Panel>
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
      {finding.evidenceHistory
        ?.filter((snapshot) => snapshot.revision !== finding.contentRevision)
        .map((snapshot) => (
          <Panel key={snapshot.revision}>
            <Copy kind="eyebrow">EARLIER FINDING EVIDENCE</Copy>
            <Copy kind="heading">{snapshot.content.title}</Copy>
            <Copy>{snapshot.content.evidence}</Copy>
            <Copy>{snapshot.content.recommendation}</Copy>
            <Copy kind="small">{snapshot.content.uncertainty}</Copy>
            {finding.annotations
              ?.filter(
                (annotation) => annotation.revision === snapshot.revision,
              )
              .slice(-1)
              .map((annotation) => (
                <FindingHighlight
                  key={annotation.id}
                  assessment={assessment}
                  finding={finding}
                  historical={annotation}
                />
              ))}
          </Panel>
        ))}
      <Section title="You make the final call">
        <Copy kind="small">
          Chat can help you consider your next step. Only you decide when a
          finding is resolved.
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
