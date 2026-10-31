import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, View } from "react-native";
import { useFocusEffect } from "expo-router";
import { apiEnabled } from "@/api/config";
import { usePreview } from "@/hooks/preview-context";
import { overviewHighlights } from "@/domain/highlights";
import type { Assessment, Finding } from "@/domain/model";
import { Button, Copy } from "@/components/ui";
import { EvidencePhoto } from "@/components/evidence-photo";
import { colors, severityColors } from "@/components/theme";

const POLL_MS = 3000;

export function SeverityLegend({ only }: { only?: Finding["severity"] }) {
  const items = (["High", "Medium", "Low"] as const).filter(
    (s) => !only || s === only,
  );
  return (
    <View
      accessibilityLabel={`Highlight colours: ${items
        .map((s) => `${severityColors[s].name} for ${s} priority`)
        .join(", ")}.`}
      accessible
      style={{ flexDirection: "row", flexWrap: "wrap", gap: 14 }}
    >
      {items.map((severity) => (
        <View
          key={severity}
          style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
        >
          <View
            style={{
              width: 14,
              height: 14,
              borderRadius: 4,
              backgroundColor: severityColors[severity].fill,
              borderWidth: 2,
              borderColor: severityColors[severity].rim,
            }}
          />
          <Copy kind="small" style={{ color: colors.ink }}>
            {severity} priority
          </Copy>
        </View>
      ))}
    </View>
  );
}

/**
 * The full original photo with every eligible open-finding highlight. Opening
 * the checklist only reads saved attempts; it never starts or retries work.
 */
export function ChecklistPhoto({ assessment }: { assessment: Assessment }) {
  const { loadMask, refreshAssessment } = usePreview();
  const overview = overviewHighlights(assessment);
  const [loaded, setLoaded] = useState<Record<string, string | null>>({});
  const requested = useRef(new Set<string>());
  const mounted = useRef(true);
  const [retryRound, setRetryRound] = useState(0);
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const ids = overview.masks.map((m) => m.annotationId).join(",");
  useEffect(() => {
    // Each mask loads independently; one failure never hides the others. Loads
    // started in an earlier round still land, so a re-run never drops them.
    for (const mask of overview.masks) {
      if (requested.current.has(mask.annotationId)) continue;
      requested.current.add(mask.annotationId);
      const finding = assessment.findings.find((f) => f.id === mask.findingId)!;
      loadMask(assessment, finding, mask.annotationId)
        .then((uri) => {
          if (mounted.current)
            setLoaded((m) => ({ ...m, [mask.annotationId]: uri }));
        })
        .catch(() => {
          requested.current.delete(mask.annotationId);
          if (mounted.current)
            setLoaded((m) => ({ ...m, [mask.annotationId]: null }));
        });
    }
  }, [ids, retryRound]);
  const failed = overview.masks.filter((m) => loaded[m.annotationId] === null);
  // Observe pending attempts (and retry failed mask reads) only while focused and active.
  const pending = overview.pending || failed.length > 0;
  useFocusEffect(
    useCallback(() => {
      if (!apiEnabled || !pending) return;
      let timer: ReturnType<typeof setTimeout> | undefined;
      let stopped = false;
      const tick = async () => {
        if (stopped || AppState.currentState !== "active") return;
        try {
          await refreshAssessment(assessment.id);
        } catch {
          /* Saved state stays visible; the next tick retries the read. */
        }
        // Failed masks stay reported until a re-read succeeds.
        if (failed.length) setRetryRound((round) => round + 1);
        if (!stopped) timer = setTimeout(() => void tick(), POLL_MS);
      };
      timer = setTimeout(() => void tick(), POLL_MS);
      const listener = AppState.addEventListener("change", (state) => {
        clearTimeout(timer);
        if (state === "active") void tick();
      });
      return () => {
        stopped = true;
        clearTimeout(timer);
        listener.remove();
      };
    }, [assessment.id, pending, failed.length]),
  );
  // Reopen/foreground return always refetches saved highlight state once.
  useFocusEffect(
    useCallback(() => {
      setHidden(false);
      if (apiEnabled && assessment.serverSaved)
        void refreshAssessment(assessment.id).catch(() => {});
    }, [assessment.id]),
  );
  const layers = overview.masks.flatMap((m) =>
    loaded[m.annotationId]
      ? [
          {
            key: m.annotationId,
            uri: loaded[m.annotationId]!,
            width: m.width,
            height: m.height,
            label: `${apiEnabled ? "AI-generated" : "Simulated"} highlight: ${
              assessment.findings.find((f) => f.id === m.findingId)?.title
            } (${m.severity})`,
          },
        ]
      : [],
  );
  const shown = layers.length;
  return (
    <View style={{ gap: 10 }}>
      <EvidencePhoto
        key={assessment.photo.id}
        photo={assessment.photo}
        masks={hidden ? [] : layers}
        dimensions={overview.masks[0]}
        caption={
          assessment.photo.sample
            ? "Sample room · illustrative photo"
            : assessment.photo.label
        }
      />
      {overview.openCount > 0 && (
        <View style={{ gap: 6 }}>
          <Button
            label={hidden ? "Show highlights" : "Hide highlights"}
            variant="secondary"
            disabled={shown === 0 && !hidden}
            onPress={() => setHidden((value) => !value)}
          />
          <Copy kind="small" accessibilityLiveRegion="polite">
            {hidden ? "Highlights hidden · " : ""}
            {`Highlights available for ${shown} of ${overview.openCount} open finding${overview.openCount === 1 ? "" : "s"}`}
            {overview.pending ? " · more may appear" : ""}
            {failed.length ? " · some could not load" : ""}
          </Copy>
          {!hidden && shown > 0 && <SeverityLegend />}
          <Copy kind="small">
            Unmarked areas have not been checked as safe.
          </Copy>
        </View>
      )}
    </View>
  );
}
