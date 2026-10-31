export type Profile = "Older adult" | "Child" | "Baby" | "Pet";
export const profiles: Profile[] = ["Older adult", "Child", "Baby", "Pet"];
export type Scenario =
  | "hazards"
  | "uncertain"
  | "clear"
  | "analysis-error"
  | "update-error"
  | "permission-denied"
  | "legacy-summary";
export const scenarios: { id: Scenario; title: string; description: string }[] =
  [
    {
      id: "hazards",
      title: "Everyday hazards",
      description: "Three findings with independent chats.",
    },
    {
      id: "uncertain",
      title: "A closer look",
      description: "One uncertain finding to investigate.",
    },
    {
      id: "clear",
      title: "No obvious hazards",
      description: "A qualified empty result.",
    },
    {
      id: "analysis-error",
      title: "Analysis retry",
      description: "First attempt fails; manual retry succeeds.",
    },
    {
      id: "update-error",
      title: "Chat reply retry",
      description: "Each chat reply stops partway once; retry replaces it.",
    },
    {
      id: "permission-denied",
      title: "Camera permission denied",
      description: "Simulated denial; gallery and samples remain available.",
    },
    {
      id: "legacy-summary",
      title: "Saved before suggestions",
      description: "An older record with a prose summary and no suggestions.",
    },
  ];
export type Photo = {
  id: string;
  label: string;
  sample?: import("./samples").Sample;
  uri?: string;
  remote?: { assessmentId: string; photoId: string };
  /** Server SHA-256 of the normalized stored photo, matched against highlight sources. */
  digest?: string;
  serverUploaded?: boolean;
};
export type Draft = {
  photo?: Photo;
  profiles: Profile[];
  scenario: Scenario;
  /** Editable, untrimmed text. Missing on older drafts, which means blank. */
  householdContext?: string;
};
export const MAX_HOUSEHOLD_DETAILS = 3000;
export const normalizeHouseholdDetails = (text = "") => text.trim();
/** Counts code points, matching the server's Python string length. */
export const householdDetailsLength = (text = "") =>
  [...normalizeHouseholdDetails(text)].length;
export function householdDetailsError(text = "") {
  return householdDetailsLength(text) > MAX_HOUSEHOLD_DETAILS
    ? "Keep household details to 3,000 characters or fewer."
    : undefined;
}
export const isDraftDirty = (draft: Draft) =>
  !!draft.photo ||
  draft.profiles.length > 0 ||
  !!normalizeHouseholdDetails(draft.householdContext);
export type FindingStatus = "open" | "resolved" | "dismissed";
export type OperationStatus = "ready" | "running" | "failed" | "complete";
export type Submission = {
  id: string;
  kind: "follow-up" | "review";
  status: OperationStatus;
  attempts: number;
  text: string;
  photo?: Photo;
  error?: string;
  feedback?: string;
  serverSaved?: boolean;
  frozen?: boolean;
};
export type Finding = {
  localChat?: import("./chat").LocalChat;
  contentRevision?: string;
  annotation?: Annotation | null;
  annotations?: Annotation[];
  evidenceHistory?: EvidenceSnapshot[];
  id: string;
  title: string;
  category: string;
  severity: "High" | "Medium" | "Low";
  evidence: string;
  recommendation: string;
  shortAction: string;
  uncertainty: string;
  status: FindingStatus;
  note: string;
  followUp?: {
    kind: "photo" | "text";
    question: string;
    state: "available" | "skipped" | "answered";
  };
  submissions: Submission[];
};
export type Assessment = {
  id: string;
  title?: string;
  createdAt: string;
  photo: Photo;
  profiles: Profile[];
  /** Normalized and frozen at creation. Missing on older records, which means blank. */
  householdContext?: string;
  scenario: Scenario;
  status: OperationStatus;
  attempts: number;
  error?: string;
  findings: Finding[];
  /** Legacy prose summary, kept as saved. New results use `suggestions`. */
  summary?: string;
  /** Undefined: legacy record. Empty: no findings. Otherwise exactly three items. */
  suggestions?: string[];
  serverSaved?: boolean;
};
export type AppState = {
  version: 1;
  assessments: Assessment[];
  draft: Draft | null;
  nextScenario: Scenario;
};
export const emptyState = (): AppState => ({
  version: 1,
  assessments: [],
  draft: null,
  nextScenario: "hazards",
});
export const makeId = () =>
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
export function createAssessment(draft: Draft): Assessment {
  if (!draft.photo) throw new Error("Choose a room photo first.");
  const invalid = householdDetailsError(draft.householdContext);
  if (invalid) throw new Error(invalid);
  return {
    id: makeId(),
    createdAt: new Date().toISOString(),
    photo: draft.photo,
    profiles: [...draft.profiles],
    householdContext: normalizeHouseholdDetails(draft.householdContext),
    scenario: draft.scenario,
    status: "ready",
    attempts: 0,
    findings: [],
  };
}
export function latest(state: AppState) {
  return state.assessments.at(-1);
}
export function destination(assessment: Assessment) {
  return assessment.status === "complete"
    ? `/assessment/${assessment.id}`
    : `/analysis/${assessment.id}`;
}
export function counts(findings: Finding[]) {
  return {
    open: findings.filter((f) => f.status === "open").length,
    resolved: findings.filter((f) => f.status === "resolved").length,
    dismissed: findings.filter((f) => f.status === "dismissed").length,
  };
}
export function ordered(findings: Finding[]) {
  const rank = { High: 0, Medium: 1, Low: 2 };
  return [...findings].sort(
    (a, b) =>
      Number(a.status !== "open") - Number(b.status !== "open") ||
      rank[a.severity] - rank[b.severity],
  );
}
export function retainedPhotos(state: AppState): Photo[] {
  return [
    state.draft?.photo,
    ...state.assessments.flatMap((a) => [
      a.photo,
      ...a.findings.flatMap((f) => f.submissions.map((s) => s.photo)),
    ]),
  ].filter((p): p is Photo => !!p);
}
export function recoverInterrupted(state: AppState): AppState {
  return {
    ...state,
    assessments: state.assessments.map((a) => ({
      ...a,
      ...(a.status === "running"
        ? {
            status: "failed" as const,
            error:
              "The preview was interrupted. Your photo is saved. Retry when you’re ready.",
          }
        : {}),
      findings: a.findings.map((f) => ({
        ...f,
        // A simulated highlight interrupted by restart finishes on reload.
        ...(f.annotation?.id?.startsWith("preview-") &&
        f.annotation.state === "processing"
          ? {
              annotation: { ...f.annotation, state: "ready" as const },
              annotations: [{ ...f.annotation, state: "ready" as const }],
            }
          : {}),
        localChat: f.localChat?.preview
          ? {
              ...f.localChat,
              preview: {
                ...f.localChat.preview,
                turns: f.localChat.preview.turns.map((t) =>
                  t.status === "running" || t.status === "queued"
                    ? {
                        ...t,
                        status: "failed" as const,
                        error:
                          "The simulated reply was interrupted. Retry when ready.",
                        error_code: "interrupted",
                        version: (t.version ?? 0) + 1,
                      }
                    : t,
                ),
              },
            }
          : f.localChat,
        submissions: f.submissions.map((s) =>
          s.status === "running"
            ? {
                ...s,
                status: "failed" as const,
                error:
                  "This check was interrupted. Your input is saved. Retry when you’re ready.",
              }
            : s,
        ),
      })),
    })),
  };
}
export function completeSubmission(
  finding: Finding,
  submissionId: string,
  feedback: string,
): Finding {
  const submission = finding.submissions.find((s) => s.id === submissionId);
  if (!submission) throw new Error("This submission is no longer available.");
  return {
    ...finding,
    // A check revises the finding's explanation, never the user's status.
    uncertainty:
      submission.kind === "follow-up"
        ? "The sample response adds context, but a photo or text answer cannot establish that the concern is resolved."
        : finding.uncertainty,
    followUp:
      submission.kind === "follow-up" && finding.followUp
        ? { ...finding.followUp, state: "answered" }
        : finding.followUp,
    submissions: finding.submissions.map((s) =>
      s.id === submissionId
        ? { ...s, status: "complete", error: undefined, feedback }
        : s,
    ),
  };
}

export type Annotation = {
  id?: string;
  revision?: string;
  attempt?: number;
  state:
    "queued" | "processing" | "ready" | "unavailable" | "failed" | "reported";
  reason?: string | null;
  supported?: boolean;
  /** False for legacy attempts without a saved prompt. */
  retryable?: boolean;
  confidence?: number | null;
  photo_id?: string | null;
  photo_kind?: "original" | "follow-up" | "review" | null;
  image_digest?: string | null;
  width?: number | null;
  height?: number | null;
  orientation?: 1;
  target?: string | null;
};
export type EvidenceSnapshot = {
  revision: string;
  content: {
    title: string;
    evidence: string;
    recommendation: string;
    uncertainty: string;
  };
  photo_ids: string[];
};
