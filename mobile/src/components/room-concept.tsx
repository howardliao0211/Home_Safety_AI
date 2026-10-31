import { useCallback, useEffect, useRef, useState } from "react";
import {
  AccessibilityInfo,
  AppState,
  Platform,
  useWindowDimensions,
  View,
} from "react-native";
import { Image } from "expo-image";
import { router, useFocusEffect } from "expo-router";
import { EvidencePhoto } from "./evidence-photo";
import { apiEnabled } from "@/api/config";
import { usePreview } from "@/hooks/preview-context";
import { conceptDisclaimer, conceptStatus } from "@/domain/room-concept";
import type { Assessment } from "@/domain/model";
import { roomSources } from "@/domain/samples";
import { Button, Copy, Notice, Screen } from "./ui";

/** Observe only while focused and active. Background jobs never depend on this poll. */
function useConceptObservation(
  id: string,
  enabled: boolean,
  attemptId?: string,
) {
  const context = usePreview();
  const latest = useRef(context);
  latest.current = context;
  const [error, setError] = useState<string>();
  useFocusEffect(
    useCallback(() => {
      if (!enabled) return;
      let active = true;
      let reading = false;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const read = async () => {
        if (!active || reading || AppState.currentState !== "active") return;
        reading = true;
        try {
          const concept = await latest.current.getRoomConcept(id);
          if (active) {
            setError(undefined);
            if (concept && ["queued", "running"].includes(concept.state))
              timer = setTimeout(() => void read(), 3000);
          }
        } catch {
          if (active) {
            setError(
              "Could not refresh the room concept. Check your connection.",
            );
            timer = setTimeout(() => void read(), 5000);
          }
        } finally {
          reading = false;
        }
      };
      void read();
      const subscription = AppState.addEventListener("change", (state) => {
        clearTimeout(timer);
        if (state === "active") void read();
      });
      return () => {
        active = false;
        clearTimeout(timer);
        subscription.remove();
      };
    }, [id, enabled, attemptId]),
  );
  return error;
}

export function RoomConceptEntry({ assessment }: { assessment: Assessment }) {
  const concept = assessment.roomConcept;
  const visible = !!concept && concept.state !== "not_applicable";
  useConceptObservation(assessment.id, visible, concept?.attempt_id);
  if (!visible) return null;
  return (
    <View style={{ gap: 6 }}>
      <Button
        label="View room concept"
        variant="secondary"
        onPress={() => router.push(`/assessment/${assessment.id}/room-concept`)}
      />
      <Copy kind="small">{conceptStatus(concept)}</Copy>
    </View>
  );
}

export function RoomConceptViewer({ assessment }: { assessment: Assessment }) {
  const { retryRoomConcept, loadRoomConceptImage } = usePreview();
  const concept = assessment.roomConcept;
  const observationError = useConceptObservation(
    assessment.id,
    !!concept,
    concept?.attempt_id,
  );
  const [error, setError] = useState<string>();
  const [retrying, setRetrying] = useState(false);
  const [uri, setUri] = useState<string>();
  const [imageAttempt, setImageAttempt] = useState(0);
  const [width, setWidth] = useState(0);
  const { fontScale } = useWindowDimensions();
  const sideBySide = width / fontScale >= 600;
  const status = concept
    ? conceptStatus(concept)
    : "No room concept for this assessment.";
  useEffect(() => {
    if (Platform.OS === "ios")
      AccessibilityInfo.announceForAccessibility(status);
  }, [status]);
  const loader = useRef(loadRoomConceptImage);
  loader.current = loadRoomConceptImage;
  useEffect(() => {
    let active = true;
    setUri(undefined);
    setError(undefined);
    if (apiEnabled && concept?.state === "ready") {
      void loader
        .current(assessment.id)
        .then((value) => {
          if (active) setUri(value);
        })
        .catch(() => {
          if (active)
            setError(
              "Could not load the saved image. Your assessment is unchanged.",
            );
        });
    }
    return () => {
      active = false;
    };
  }, [assessment.id, concept?.state, concept?.attempt_id, imageAttempt]);
  const source = apiEnabled ? (uri ? { uri } : undefined) : roomSources.quiet;
  const ratio =
    concept?.width && concept.height ? concept.width / concept.height : 4 / 3;
  return (
    <Screen>
      <Copy kind="title" accessibilityRole="header">
        AI-generated room concept
      </Copy>
      <Copy>{conceptDisclaimer}</Copy>
      {!apiEnabled && (
        <Copy kind="small">
          Simulated concept: this sample image is not an edit of your room.
        </Copy>
      )}
      <View
        onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
        style={{
          flexDirection: sideBySide ? "row" : "column",
          alignItems: "flex-start",
          gap: 24,
        }}
      >
        <View
          style={{
            gap: 12,
            width: sideBySide ? undefined : "100%",
            flex: sideBySide ? 1 : undefined,
            minWidth: 0,
          }}
        >
          <Copy kind="heading" accessibilityRole="header">
            Original room
          </Copy>
          <EvidencePhoto key={assessment.photo.id} photo={assessment.photo} />
        </View>
        <View
          style={{
            gap: 12,
            width: sideBySide ? undefined : "100%",
            flex: sideBySide ? 1 : undefined,
            minWidth: 0,
          }}
        >
          <Copy kind="heading" accessibilityRole="header">
            Generated room concept
          </Copy>
          <Copy accessibilityLiveRegion="polite">{status}</Copy>
          {!!observationError && (
            <Notice title="Connection unavailable">
              <Copy>{observationError}</Copy>
            </Notice>
          )}
          {concept && ["queued", "running"].includes(concept.state) && (
            <Copy>
              You can return to your checklist. Generation continues in the
              background.
            </Copy>
          )}
          {concept?.state === "ready" &&
            (error ? (
              <Notice title="Image unavailable">
                <Copy>{error}</Copy>
                <Button
                  label="Retry loading image"
                  variant="secondary"
                  onPress={() => setImageAttempt((n) => n + 1)}
                />
              </Notice>
            ) : source ? (
              <Image
                source={source}
                cachePolicy="none"
                contentFit="contain"
                accessibilityLabel="AI-generated room concept illustrating suggested changes, not evidence of safety"
                style={{ width: "100%", aspectRatio: ratio }}
                onError={() =>
                  setError(
                    "Could not display the saved image. Your assessment is unchanged.",
                  )
                }
              />
            ) : (
              <Copy>Loading saved room concept…</Copy>
            ))}
          {concept?.state === "failed" && concept.can_retry && (
            <>
              {!!error && <Copy accessibilityLiveRegion="polite">{error}</Copy>}
              <Button
                label="Retry room concept"
                disabled={retrying}
                loading={retrying}
                onPress={() => {
                  setRetrying(true);
                  setError(undefined);
                  void retryRoomConcept(assessment.id)
                    .catch(() =>
                      setError(
                        "Could not retry. Check your connection and try again.",
                      ),
                    )
                    .finally(() => setRetrying(false));
                }}
              />
            </>
          )}
        </View>
      </View>
      <Button
        label="Back to checklist"
        variant="secondary"
        onPress={() => router.dismissTo(`/assessment/${assessment.id}`)}
      />
    </Screen>
  );
}
