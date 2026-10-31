import type {
  Annotation,
  Assessment,
  Finding,
  FindingStatus,
  Photo,
  Profile,
  Submission,
} from "../domain/model";
import type { HistoryItem } from "../domain/history";

import { mergeRoomConcept, type RoomConcept } from "../domain/room-concept";

type RemotePhoto = { id: string; uploaded: boolean; sha256?: string };
type RemoteOperation = {
  status: Assessment["status"];
  attempts: number;
  error: string | null;
};
type RemoteSubmission = RemoteOperation & {
  id: string;
  kind: Submission["kind"];
  text: string;
  photo: RemotePhoto | null;
  feedback: string | null;
};
type RemoteFinding = Omit<
  Finding,
  "shortAction" | "followUp" | "submissions"
> & {
  content_revision?: string;
  evidence_history?: Finding["evidenceHistory"];
  short_action: string;
  follow_up: Finding["followUp"] | null;
  submissions: RemoteSubmission[];
};
export type RemoteAssessment = RemoteOperation & {
  room_concept?: RoomConcept | null;
  id: string;
  title?: string | null;
  created_at: string;
  photo: RemotePhoto;
  profiles: Profile[];
  /** Absent only on records saved before the field existed. */
  household_context?: string;
  summary: string | null;
  /** Null/absent on legacy records saved before structured suggestions. */
  suggestions?: string[] | null;
  findings: RemoteFinding[];
};

function photoFromServer(
  photo: RemotePhoto,
  assessmentId: string,
  cached?: Photo,
): Photo {
  return {
    ...cached,
    id: photo.id,
    label: cached?.label || "Your saved room photo",
    ...(photo.sha256 ? { digest: photo.sha256 } : {}),
    remote: { assessmentId, photoId: photo.id },
    serverUploaded: photo.uploaded,
  };
}

export function fromServer(
  remote: RemoteAssessment,
  cached?: Assessment,
): Assessment {
  return {
    id: remote.id,
    roomConcept: remote.room_concept
      ? mergeRoomConcept(cached?.roomConcept, remote.room_concept)
      : undefined,
    title: remote.title || undefined,
    createdAt: remote.created_at,
    profiles: remote.profiles,
    householdContext:
      remote.household_context ?? cached?.householdContext ?? "",
    status: remote.status,
    attempts: remote.attempts,
    error: remote.error || undefined,
    summary: remote.summary || undefined,
    suggestions: remote.suggestions ?? undefined,
    serverSaved: true,
    scenario: cached?.scenario || "hazards",
    photo: photoFromServer(remote.photo, remote.id, cached?.photo),
    findings: remote.findings.map((item) => {
      const old = cached?.findings.find((f) => f.id === item.id);
      return {
        id: item.id,
        localChat: old?.localChat,
        contentRevision: item.content_revision || "initial",
        annotation: item.annotation,
        annotations: item.annotations || [],
        evidenceHistory: item.evidence_history || [],
        title: item.title,
        category: item.category,
        severity: item.severity,
        evidence: item.evidence,
        recommendation: item.recommendation,
        shortAction: item.short_action,
        uncertainty: item.uncertainty,
        status: item.status,
        note: item.note,
        followUp: item.follow_up || undefined,
        submissions: [
          ...item.submissions.map((s) => {
            const previous = old?.submissions.find((p) => p.id === s.id);
            return {
              id: s.id,
              kind: s.kind,
              status: s.status,
              attempts: s.attempts,
              text: s.text,
              photo: s.photo
                ? photoFromServer(s.photo, remote.id, previous?.photo)
                : undefined,
              error: s.error || undefined,
              feedback: s.feedback || undefined,
              serverSaved: true,
              frozen: true,
            };
          }),
          ...(old?.submissions.filter(
            (s) =>
              !s.serverSaved && !item.submissions.some((r) => r.id === s.id),
          ) || []),
        ],
      };
    }),
  };
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
  ) {
    super(message);
  }
}

export class BackendClient {
  constructor(
    private config: {
      baseUrl: string;
      getToken: () => Promise<string>;
      onAuthError?: (error: ApiError) => void | Promise<void>;
    },
    private appendPhoto: (form: FormData, photo: Photo) => Promise<void>,
    private fetcher: typeof fetch = fetch,
  ) {}

  private disposed = false;
  private pending = new Set<AbortController>();
  dispose() {
    this.disposed = true;
    this.pending.forEach((controller) => controller.abort());
    this.pending.clear();
  }
  private assertActive() {
    if (this.disposed) throw new Error("The account session has changed.");
  }
  private async request(
    path: string,
    init: RequestInit = {},
  ): Promise<Response> {
    this.assertActive();
    const abort = new AbortController();
    this.pending.add(abort);
    const timer = setTimeout(() => abort.abort(), 310_000);
    try {
      const headers = new Headers(init.headers);
      const token = await this.config.getToken();
      this.assertActive();
      headers.set("Authorization", `Bearer ${token}`);
      // Browser fetch rejects a BackendClient instance as its receiver.
      const fetcher = this.fetcher;
      const response = await fetcher(this.config.baseUrl + path, {
        ...init,
        headers,
        signal: abort.signal,
      });
      this.assertActive();
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        const error = new ApiError(
          body?.error?.message ||
            `The request failed (HTTP ${response.status}).`,
          response.status,
          body?.error?.code || "request_failed",
        );
        if (error.status === 401 || error.code === "account_deleting")
          await this.config.onAuthError?.(error);
        throw error;
      }
      return response;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new Error(
        abort.signal.aborted
          ? "The request timed out. Your input is saved. Retry when ready."
          : "Could not reach the assessment service. Check your connection and retry.",
      );
    } finally {
      clearTimeout(timer);
      this.pending.delete(abort);
    }
  }

  private async assessment(
    path: string,
    cached?: Assessment,
    init?: RequestInit,
  ) {
    return fromServer(await (await this.request(path, init)).json(), cached);
  }
  async latest(cached: Assessment[] = []): Promise<Assessment | null> {
    try {
      const dto: RemoteAssessment = await (
        await this.request("/v1/assessments/latest")
      ).json();
      const previous = cached.find((a) => a.id === dto.id);
      const restored = fromServer(dto, previous);
      // A ready server record may be a retained failed upload, or an analysis
      // interrupted before it started. Restoring it must not trigger a model call.
      if (restored.status === "ready") {
        restored.status = "failed";
        restored.error =
          previous?.error ||
          "This assessment has unfinished analysis. Your input is saved. Retry when ready.";
      }
      return restored;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  }
  get(assessment: Assessment) {
    return this.assessment(`/v1/assessments/${assessment.id}`, assessment);
  }
  async open(id: string, cached?: Assessment) {
    const restored = await this.assessment(`/v1/assessments/${id}`, cached);
    // Opening a retained upload must never initiate analysis automatically.
    if (restored.status === "ready") {
      restored.status = "failed";
      restored.error =
        "This assessment has unfinished analysis. Your input is saved. Retry when ready.";
    }
    return restored;
  }
  async history(
    cursor?: string,
  ): Promise<{ items: HistoryItem[]; nextCursor?: string }> {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
    const page: {
      items: {
        id: string;
        title?: string | null;
        created_at: string;
        status: Assessment["status"];
        open_count: number | null;
        photo: RemotePhoto;
      }[];
      next_cursor: string | null;
    } = await (await this.request(`/v1/assessments${query}`)).json();
    return {
      items: page.items.map((item) => ({
        id: item.id,
        title: item.title || undefined,
        createdAt: item.created_at,
        status: item.status,
        openCount: item.open_count,
        photo: photoFromServer(item.photo, item.id),
      })),
      nextCursor: page.next_cursor || undefined,
    };
  }
  async upload(assessment: Assessment) {
    if (assessment.serverSaved && assessment.photo.serverUploaded)
      return assessment;
    const form = new FormData();
    form.append("assessment_id", assessment.id);
    form.append("profiles", JSON.stringify(assessment.profiles));
    form.append("household_context", assessment.householdContext ?? "");
    await this.appendPhoto(form, assessment.photo);
    return this.assessment("/v1/assessments", assessment, {
      method: "POST",
      body: form,
    });
  }
  analyze(assessment: Assessment) {
    return this.assessment(
      `/v1/assessments/${assessment.id}/analyze`,
      assessment,
      { method: "POST" },
    );
  }
  patch(
    assessment: Assessment,
    findingId: string,
    status: FindingStatus,
    note?: string,
  ) {
    return this.assessment(
      `/v1/assessments/${assessment.id}/findings/${findingId}`,
      assessment,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status,
          ...(note === undefined ? {} : { note }),
        }),
      },
    );
  }
  skip(assessment: Assessment, findingId: string) {
    return this.assessment(
      `/v1/assessments/${assessment.id}/findings/${findingId}/skip-follow-up`,
      assessment,
      { method: "POST" },
    );
  }
  async uploadSubmission(
    assessment: Assessment,
    finding: Finding,
    input: Submission,
  ) {
    if (input.serverSaved && (!input.photo || input.photo.serverUploaded))
      return assessment;
    const form = new FormData();
    form.append("submission_id", input.id);
    form.append("kind", input.kind);
    form.append("text", input.text);
    if (input.photo) await this.appendPhoto(form, input.photo);
    return this.assessment(
      `/v1/assessments/${assessment.id}/findings/${finding.id}/submissions`,
      assessment,
      { method: "POST", body: form },
    );
  }
  check(assessment: Assessment, findingId: string, submissionId: string) {
    return this.assessment(
      `/v1/assessments/${assessment.id}/findings/${findingId}/submissions/${submissionId}/analyze`,
      assessment,
      { method: "POST" },
    );
  }
  async delete(id: string) {
    await this.request(`/v1/assessments/${id}`, { method: "DELETE" });
  }
  /** Explicit user retry of an initial highlight, using its saved prompt. */
  async retryAnnotation(
    assessmentId: string,
    findingId: string,
    revision: string,
  ): Promise<Annotation> {
    return (
      await this.request(
        `/v1/assessments/${assessmentId}/findings/${findingId}/annotations`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ revision, retry: true }),
        },
      )
    ).json();
  }
  async annotation(
    assessmentId: string,
    findingId: string,
    id: string,
  ): Promise<Annotation> {
    return (
      await this.request(
        `/v1/assessments/${assessmentId}/findings/${findingId}/annotations/${id}`,
      )
    ).json();
  }
  async reportAnnotation(
    assessmentId: string,
    findingId: string,
    id: string,
  ): Promise<Annotation> {
    return (
      await this.request(
        `/v1/assessments/${assessmentId}/findings/${findingId}/annotations/${id}/feedback`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "wrong_object" }),
        },
      )
    ).json();
  }
  private chatPath(assessmentId: string, findingId: string) {
    return `/v1/assessments/${assessmentId}/findings/${findingId}/chat`;
  }
  async chat(
    assessmentId: string,
    findingId: string,
  ): Promise<import("../domain/chat").Conversation> {
    return (await this.request(this.chatPath(assessmentId, findingId))).json();
  }
  async acceptChat(
    assessmentId: string,
    findingId: string,
    body: { id: string; question: string },
  ): Promise<import("../domain/chat").Conversation> {
    return (
      await this.request(this.chatPath(assessmentId, findingId) + "/turns", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
    ).json();
  }
  async generateChat(
    assessmentId: string,
    findingId: string,
    turnId: string,
    attemptId: string,
  ): Promise<import("../domain/chat").Conversation> {
    return (
      await this.request(
        this.chatPath(assessmentId, findingId) + `/turns/${turnId}/generate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ attempt_id: attemptId }),
        },
      )
    ).json();
  }
  async roomConcept(assessmentId: string): Promise<RoomConcept> {
    return (
      await this.request(`/v1/assessments/${assessmentId}/room-concept`)
    ).json();
  }
  async retryRoomConcept(
    assessmentId: string,
    attemptId: string,
  ): Promise<RoomConcept> {
    return (
      await this.request(`/v1/assessments/${assessmentId}/room-concept/retry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ attempt_id: attemptId }),
      })
    ).json();
  }
  async roomConceptImage(assessmentId: string) {
    return this.dataUrl(
      await this.request(`/v1/assessments/${assessmentId}/room-concept/image`),
      "image/jpeg",
    );
  }
  async maskDataUrl(assessmentId: string, findingId: string, id: string) {
    return this.dataUrl(
      await this.request(
        `/v1/assessments/${assessmentId}/findings/${findingId}/annotations/${id}/mask`,
      ),
      "image/png",
    );
  }
  async photoDataUrl(photo: NonNullable<Photo["remote"]>) {
    const response = await this.request(
      `/v1/assessments/${photo.assessmentId}/photos/${photo.photoId}`,
    );
    return this.dataUrl(response, "image/jpeg");
  }
  private async dataUrl(response: Response, contentType: string) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    this.assertActive();
    const alphabet =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let encoded = "";
    for (let i = 0; i < bytes.length; i += 3) {
      const n =
        (bytes[i] << 16) | ((bytes[i + 1] || 0) << 8) | (bytes[i + 2] || 0);
      encoded +=
        alphabet[(n >>> 18) & 63] +
        alphabet[(n >>> 12) & 63] +
        (i + 1 < bytes.length ? alphabet[(n >>> 6) & 63] : "=") +
        (i + 2 < bytes.length ? alphabet[n & 63] : "=");
    }
    return `data:${contentType};base64,${encoded}`;
  }
}
