export type RoomConcept = {
  state:
    | "not_applicable"
    | "unavailable"
    | "queued"
    | "running"
    | "ready"
    | "failed";
  attempt_id?: string;
  attempt?: number;
  can_retry: boolean;
  error?: string | null;
  width?: number | null;
  height?: number | null;
  /** Preview-only clock; never starts a provider request. */
  previewReadyAt?: number;
};

export const conceptDisclaimer =
  "An illustration of suggested changes based on the original assessment. It may miss hazards or show inaccurate changes. It does not mean your room is safe.";

export function conceptStatus(concept: RoomConcept) {
  switch (concept.state) {
    case "queued":
    case "running":
      return "Generating room concept…";
    case "ready":
      return "Your room concept is ready";
    case "failed":
      return concept.can_retry
        ? "Room concept could not finish. Retry when ready."
        : "Room concept could not finish. The retry limit has been reached.";
    case "unavailable":
      return "Room concepts are currently unavailable.";
    default:
      return "No room concept for this assessment.";
  }
}

export function mergeRoomConcept(
  previous: RoomConcept | undefined,
  incoming: RoomConcept,
): RoomConcept {
  if (!previous) return incoming;
  if ((previous.attempt ?? 0) > (incoming.attempt ?? 0)) return previous;
  const rank = {
    not_applicable: 0,
    unavailable: 0,
    queued: 1,
    running: 2,
    failed: 3,
    ready: 4,
  };
  if (
    previous.attempt_id === incoming.attempt_id &&
    rank[previous.state] > rank[incoming.state]
  )
    return previous;
  return incoming;
}

export function previewRoomConcept(
  scenario: string,
  hasFindings: boolean,
  unavailable = false,
): RoomConcept {
  return {
    state: !hasFindings
      ? "not_applicable"
      : unavailable
        ? "unavailable"
        : scenario === "uncertain"
          ? "failed"
          : "queued",
    can_retry: hasFindings && scenario === "uncertain" && !unavailable,
    attempt: 1,
    attempt_id: "preview-1",
    previewReadyAt: Date.now() + 8000,
    width: 1200,
    height: 816,
  };
}
