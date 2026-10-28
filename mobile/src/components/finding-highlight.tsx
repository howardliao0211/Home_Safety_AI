import { useCallback, useRef, useState } from "react";
import { AppState, View } from "react-native";
import { useFocusEffect } from "expo-router";
import { apiEnabled } from "@/api/config";
import { ApiError } from "@/api/backend-client";
import { usePreview } from "@/hooks/preview-context";
import type { Annotation, Assessment, Finding } from "@/domain/model";
import { Button, Copy } from "@/components/ui";
import { EvidencePhoto } from "@/components/evidence-photo";

const ACTIVE = ["queued", "processing"];

function newer(a: Annotation | null, b: Annotation | null) {
  if (!a) return b;
  if (!b) return a;
  return (b.attempt || 0) > (a.attempt || 0) ? b : a;
}

/**
 * The backend starts highlight work when the assessment completes. Opening a
 * finding only reads that saved attempt; it never creates or retries model work
 * except through the explicit Retry button.
 */
export function FindingHighlight({
  assessment,
  finding,
  historical,
}: {
  assessment: Assessment;
  finding: Finding;
  historical?: Annotation;
}) {
  const { annotationClient, refreshAssessment } = usePreview();
  const revision = historical?.revision || finding.contentRevision || "initial";
  const saved = historical || finding.annotation || null;
  const [annotation, setAnnotation] = useState<Annotation | null>(saved);
  const [mask, setMask] = useState<string>();
  const [hidden, setHidden] = useState(false);
  const [error, setError] = useState<string>();
  const [acting, setActing] = useState(false);
  const action = useRef(false);
  const latest = useRef<Annotation | null>(saved);
  latest.current =
    historical || newer(latest.current, finding.annotation || null);
  const current =
    annotation?.revision === revision || annotation?.supported === false
      ? annotation
      : null;
  const [pollAttempt, setPollAttempt] = useState(0);
  const generation = useRef(0);
  const apply = useCallback(
    async (value: Annotation, token: number) => {
      if (token !== generation.current) return false;
      if (value.id) latest.current = value;
      setAnnotation(value);
      setError(undefined);
      setMask(undefined);
      if (
        value.state === "ready" &&
        value.id &&
        value.photo_id &&
        value.width &&
        value.height &&
        value.orientation === 1
      ) {
        try {
          const uri = await (
            await annotationClient()
          ).maskDataUrl(assessment.id, finding.id, value.id);
          if (token === generation.current) setMask(uri);
        } catch (e) {
          if (token === generation.current)
            setError(
              e instanceof Error ? e.message : "Could not load highlight.",
            );
          return false;
        }
      }
      return true;
    },
    [assessment.id, finding.id],
  );
  useFocusEffect(
    useCallback(() => {
      const token = ++generation.current;
      let timer: ReturnType<typeof setTimeout> | undefined;
      let last = latest.current;
      setHidden(false);
      setMask(undefined);
      let checking = false;
      let assetFailed = false;
      let readFailed = false;
      const stop = () => {
        clearTimeout(timer);
        timer = undefined;
      };
      const check = async () => {
        // One read at a time per attempt, and only while the screen is visible.
        if (
          !apiEnabled ||
          !last?.id ||
          token !== generation.current ||
          checking ||
          action.current ||
          AppState.currentState !== "active"
        )
          return;
        stop();
        checking = true;
        try {
          readFailed = false;
          if (last.state === "ready" && assetFailed) {
            assetFailed = !(await apply(last, token));
            return;
          }
          const api = await annotationClient();
          last = await api.annotation(assessment.id, finding.id, last.id!);
          assetFailed = !(await apply(last, token));
        } catch (e) {
          if (token !== generation.current) return;
          readFailed = true;
          if (e instanceof ApiError && e.status === 409) {
            try {
              await refreshAssessment(assessment.id);
            } catch {
              /* Retry on reconnect. */
            }
          }
          if (token === generation.current)
            setError(e instanceof Error ? e.message : "Highlight unavailable.");
        } finally {
          checking = false;
          if (
            token === generation.current &&
            AppState.currentState === "active" &&
            (assetFailed || readFailed || ACTIVE.includes(last?.state || ""))
          )
            timer = setTimeout(() => void check(), 2000);
        }
      };
      void check();
      const listener = AppState.addEventListener("change", (state) => {
        // Saved state is authoritative after inactivity; work never paused.
        if (state === "active") void check();
        else stop();
      });
      return () => {
        generation.current++;
        stop();
        listener.remove();
      };
    }, [assessment.id, finding.id, revision, historical?.id, pollAttempt]),
  );

  async function act(report: boolean) {
    if (action.current) return;
    action.current = true;
    setActing(true);
    if (report) setHidden(true);
    const token = ++generation.current;
    try {
      const api = await annotationClient();
      const result =
        report && current?.id
          ? await api.reportAnnotation(assessment.id, finding.id, current.id)
          : await api.retryAnnotation(assessment.id, finding.id, revision);
      if (token !== generation.current) return;
      setHidden(false);
      await apply(result, token);
      // Resume reading the new attempt; the operation is owned by the server.
      if (!report) setPollAttempt((value) => value + 1);
    } catch (e) {
      if (token === generation.current)
        setError(
          e instanceof Error ? e.message : "Could not save highlight action.",
        );
    } finally {
      action.current = false;
      setActing(false);
    }
  }
  const sourcePhoto = current?.photo_id
    ? [assessment.photo, ...finding.submissions.map((s) => s.photo)].find(
        (photo) => photo?.id === current.photo_id,
      )
    : assessment.photo;
  const photo = sourcePhoto
    ? {
        ...sourcePhoto,
        label: current?.photo_kind
          ? `${current.photo_kind === "original" ? "Original" : current.photo_kind === "review" ? "Review" : "Follow-up"} evidence photo`
          : sourcePhoto.label,
      }
    : assessment.photo;
  const status = !current
    ? revision === "initial"
      ? "No highlight is available for this finding."
      : "Highlights are made only for the original assessment findings."
    : current.state === "queued"
      ? "Highlight queued…"
      : current.state === "processing"
        ? "Preparing highlight…"
        : current.state === "ready"
          ? "AI-generated highlight · may mark the wrong object · not safety verification"
          : current.reason || "Highlight unavailable.";
  return (
    <View style={{ gap: 10 }}>
      <EvidencePhoto
        key={photo.id}
        photo={photo}
        dimensions={
          current?.width && current.height
            ? { width: current.width, height: current.height }
            : undefined
        }
        mask={
          sourcePhoto && current?.state === "ready" && !hidden
            ? mask
            : undefined
        }
      />
      {!apiEnabled ? (
        <Copy kind="small">
          Object highlighting is unavailable in preview mode.
        </Copy>
      ) : (
        <>
          <Copy kind="small" accessibilityLiveRegion="polite">
            {status}
          </Copy>
          {!!error && <Copy kind="small">{error}</Copy>}
          {current?.state === "ready" && (
            <>
              <Button
                label={hidden ? "Show highlights" : "Hide highlights"}
                variant="text"
                onPress={() => setHidden((value) => !value)}
              />
              <Button
                label="Wrong object highlighted"
                variant="text"
                disabled={acting}
                onPress={() => void act(true)}
              />
            </>
          )}
          {!!error && (
            <Button
              label="Reload highlight"
              variant="secondary"
              onPress={() => setPollAttempt((value) => value + 1)}
            />
          )}
          {!historical &&
            current &&
            ["failed", "unavailable", "reported"].includes(current.state) &&
            current.retryable !== false &&
            current.supported !== false && (
              <Button
                label="Retry highlight"
                variant="secondary"
                disabled={acting}
                onPress={() => void act(false)}
              />
            )}
        </>
      )}
    </View>
  );
}
