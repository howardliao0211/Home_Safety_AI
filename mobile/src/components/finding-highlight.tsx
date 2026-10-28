import { useCallback, useRef, useState } from "react";
import { AppState, View } from "react-native";
import { useFocusEffect } from "expo-router";
import { apiEnabled } from "@/api/config";
import { ApiError } from "@/api/backend-client";
import { usePreview } from "@/hooks/preview-context";
import type { Annotation, Assessment, Finding } from "@/domain/model";
import { Button, Copy } from "@/components/ui";
import { EvidencePhoto } from "@/components/evidence-photo";

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
  const [annotation, setAnnotation] = useState<Annotation | null>(
    historical || finding.annotation || null,
  );
  const [mask, setMask] = useState<string>();
  const [hidden, setHidden] = useState(false);
  const [error, setError] = useState<string>();
  const [acting, setActing] = useState(false);
  const action = useRef(false);
  const current =
    annotation?.revision === revision || annotation?.supported === false
      ? annotation
      : null;
  const [pollAttempt, setPollAttempt] = useState(0);
  const generation = useRef(0);
  const apply = useCallback(
    async (value: Annotation, token: number) => {
      if (token !== generation.current) return;
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
        }
      }
    },
    [assessment.id, finding.id],
  );
  useFocusEffect(
    useCallback(() => {
      const token = ++generation.current;
      let timer: ReturnType<typeof setTimeout>;
      let last: Annotation | null = historical || null;
      setHidden(false);
      setMask(undefined);
      let checking = false;
      const check = async () => {
        if (token !== generation.current || checking || action.current) return;
        checking = true;
        try {
          if (!apiEnabled) return;
          const api = await annotationClient();
          last = historical?.id
            ? await api.annotation(assessment.id, finding.id, historical.id)
            : last?.id
              ? await api.annotation(assessment.id, finding.id, last.id)
              : await api.requestAnnotation(
                  assessment.id,
                  finding.id,
                  revision,
                );
          await apply(last, token);
        } catch (e) {
          if (e instanceof ApiError && e.status === 409)
            await refreshAssessment(assessment.id);
          if (token === generation.current)
            setError(e instanceof Error ? e.message : "Highlight unavailable.");
        } finally {
          checking = false;
          if (
            token === generation.current &&
            (!last || ["queued", "processing"].includes(last.state))
          )
            timer = setTimeout(() => void check(), 2000);
        }
      };
      void check();
      const listener = AppState.addEventListener("change", (state) => {
        if (state === "active") void check();
      });
      return () => {
        generation.current++;
        clearTimeout(timer);
        listener.remove();
      };
    }, [assessment.id, finding.id, revision, historical?.id, pollAttempt]),
  );

  async function act(report: boolean) {
    if (action.current) return;
    action.current = true;
    setActing(true);
    const token = generation.current;
    try {
      const api = await annotationClient();
      const result =
        report && current?.id
          ? await api.reportAnnotation(assessment.id, finding.id, current.id)
          : await api.requestAnnotation(
              assessment.id,
              finding.id,
              revision,
              true,
            );
      setHidden(false);
      await apply(result, token);
      // Restart polling for the new attempt; the operation is owned by the server.
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
            {current?.state === "queued"
              ? "Highlight queued…"
              : current?.state === "processing"
                ? "Preparing highlight…"
                : current?.reason ||
                  (current?.state === "ready"
                    ? "Reviewed object location · not safety verification"
                    : "Requesting highlight…")}
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
          {!historical &&
            (error ||
              (current &&
                ["failed", "unavailable", "reported"].includes(
                  current.state,
                ))) &&
            current?.supported !== false && (
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
