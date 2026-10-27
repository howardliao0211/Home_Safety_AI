import { useEffect, useState } from "react";
import { ActivityIndicator, TextInput, View } from "react-native";
import { Redirect, router, useLocalSearchParams } from "expo-router";
import { useNavigation, usePreventRemove } from "expo-router/react-navigation";
import { usePreview } from "@/hooks/preview-context";
import { PhotoInput } from "@/components/photo-input";
import {
  Button,
  Copy,
  Disclaimer,
  Notice,
  PreviewNotice,
  Screen,
  styles,
} from "@/components/ui";
import { colors } from "@/components/theme";

export default function EvidenceScreen() {
  const {
    assessmentId,
    findingId,
    kind: requestedKind,
  } = useLocalSearchParams<{
    assessmentId: string;
    findingId: string;
    kind?: string;
  }>();
  const kind = requestedKind === "review" ? "review" : "follow-up";
  const { state, busy, saveInput, runCheck, skip } = usePreview();
  const assessment = state.assessments.find((a) => a.id === assessmentId);
  const finding = assessment?.findings.find((f) => f.id === findingId);
  const submission = finding?.submissions.find(
    (s) => s.kind === kind && s.status !== "complete",
  );
  const completed = finding?.submissions
    .filter((s) => s.kind === kind && s.status === "complete")
    .at(-1);
  const [text, setText] = useState(submission?.text ?? "");
  const [finished, setFinished] = useState(false);
  const [invalidPhoto, setInvalidPhoto] = useState(false);
  useEffect(() => setInvalidPhoto(false), [submission?.photo?.id]);
  const navigation = useNavigation();
  const needsText = kind === "follow-up" && finding?.followUp?.kind === "text";
  // Save an edited answer before back navigation; failed storage leaves the user
  // on this page with their input and a visible error.
  usePreventRemove(
    !!needsText &&
      !finished &&
      text !== (submission?.text ?? completed?.text ?? ""),
    ({ data }) => {
      void saveInput(assessmentId, findingId, kind, { text }).then((ok) => {
        if (ok) navigation.dispatch(data.action);
      });
    },
  );
  const handledFollowUp =
    kind === "follow-up" &&
    !!finding &&
    finding.followUp?.state !== "available";
  useEffect(() => {
    if (handledFollowUp)
      router.dismissTo(`/finding/${assessmentId}/${findingId}`);
  }, [handledFollowUp, assessmentId, findingId]);
  if (!assessment || !finding) return <Redirect href="/" />;
  if (handledFollowUp) return null;
  async function submit() {
    if (needsText) {
      const saved = await saveInput(assessmentId, findingId, kind, { text });
      if (!saved) return;
    }
    await runCheck(assessmentId, findingId, kind);
    setFinished(true);
  }
  const feedback = finished && !submission ? completed : undefined;
  const pending = busy && submission?.status === "running";
  return (
    <Screen>
      <Copy kind="eyebrow">
        {kind === "review"
          ? "YOUR REQUEST · PHOTO REVIEW"
          : "ONE FOLLOW-UP · OPTIONAL"}
      </Copy>
      <Copy kind="title" accessibilityRole="header">
        {kind === "review"
          ? "Another view.\nYour decision."
          : needsText
            ? "A little more context."
            : "Take a closer look."}
      </Copy>
      <Copy kind="heading">{finding.title}</Copy>
      <PreviewNotice />
      <Copy>
        {kind === "review"
          ? "Add a new photo linked to this finding. The simulated feedback will not mark it resolved."
          : finding.followUp?.question}
      </Copy>
      {feedback ? (
        <Notice title="Simulated review received" tone="success">
          <Copy>{feedback.feedback}</Copy>
          <Button
            label="Return to finding"
            onPress={() =>
              router.dismissTo(`/finding/${assessmentId}/${findingId}`)
            }
          />
        </Notice>
      ) : (
        <>
          {needsText ? (
            <View style={{ gap: 10 }}>
              <Copy kind="small">Your answer</Copy>
              <TextInput
                accessibilityLabel="Your answer"
                value={text}
                onChangeText={setText}
                placeholder="Tell us how your household uses this area…"
                placeholderTextColor={colors.muted}
                multiline
                editable={!busy}
                style={styles.input}
              />
              <Copy kind="small">
                Your answer is saved when you submit or leave this page.
              </Copy>
            </View>
          ) : (
            <PhotoInput
              photo={submission?.photo}
              onInvalid={() => setInvalidPhoto(true)}
              denyCamera={assessment.scenario === "permission-denied"}
              onChange={(photo) =>
                saveInput(assessmentId, findingId, kind, { photo })
              }
            />
          )}
          {pending && (
            <View style={styles.row}>
              <ActivityIndicator color={colors.accent} />
              <Copy accessibilityLiveRegion="polite">
                Preparing simulated feedback…
              </Copy>
            </View>
          )}
          {submission?.error && (
            <Notice title="The check could not finish" tone="error">
              <Copy>{submission.error}</Copy>
            </Notice>
          )}
          {submission?.status === "running" && !busy && (
            <Notice title="The result could not be saved" tone="error">
              <Copy>Your existing finding is unchanged. Retry this check.</Copy>
            </Notice>
          )}
          <Button
            label={
              submission?.status === "failed" ||
              (submission?.status === "running" && !busy)
                ? "Retry check"
                : kind === "review"
                  ? "Request sample photo review"
                  : "Submit follow-up"
            }
            icon="arrow"
            disabled={
              needsText ? !text.trim() : !submission?.photo || invalidPhoto
            }
            loading={pending}
            onPress={() => void submit()}
          />
          {kind === "follow-up" && !submission && !text && (
            <Button
              label="Skip for now"
              variant="text"
              onPress={() => void skip(assessmentId, findingId)}
            />
          )}
          <Button
            label="Back to finding"
            variant="text"
            onPress={() =>
              router.dismissTo(`/finding/${assessmentId}/${findingId}`)
            }
          />
        </>
      )}
      <Disclaimer />
    </Screen>
  );
}
