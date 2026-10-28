import type {
  Annotation,
  Assessment,
  Finding,
  FindingStatus,
  Photo,
  Profile,
  Submission,
} from "../domain/model";

type RemotePhoto = { id: string; uploaded: boolean };
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
  id: string;
  created_at: string;
  photo: RemotePhoto;
  profiles: Profile[];
  summary: string | null;
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
    createdAt: remote.created_at,
    profiles: remote.profiles,
    status: remote.status,
    attempts: remote.attempts,
    error: remote.error || undefined,
    summary: remote.summary || undefined,
    serverSaved: true,
    scenario: cached?.scenario || "hazards",
    photo: photoFromServer(remote.photo, remote.id, cached?.photo),
    findings: remote.findings.map((item) => {
      const old = cached?.findings.find((f) => f.id === item.id);
      return {
        id: item.id,
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
    private config: { baseUrl: string; demoToken: string; deviceId: string },
    private appendPhoto: (form: FormData, photo: Photo) => Promise<void>,
    private fetcher: typeof fetch = fetch,
  ) {}

  private async request(
    path: string,
    init: RequestInit = {},
  ): Promise<Response> {
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), 310_000);
    try {
      const headers = new Headers(init.headers);
      headers.set("X-Device-ID", this.config.deviceId);
      if (this.config.demoToken)
        headers.set("Authorization", `Bearer ${this.config.demoToken}`);
      // Browser fetch rejects a BackendClient instance as its receiver.
      const fetcher = this.fetcher;
      const response = await fetcher(this.config.baseUrl + path, {
        ...init,
        headers,
        signal: abort.signal,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new ApiError(
          body?.error?.message ||
            `The request failed (HTTP ${response.status}).`,
          response.status,
          body?.error?.code || "request_failed",
        );
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
  async upload(assessment: Assessment) {
    if (assessment.serverSaved && assessment.photo.serverUploaded)
      return assessment;
    const form = new FormData();
    form.append("assessment_id", assessment.id);
    form.append("profiles", JSON.stringify(assessment.profiles));
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
  async requestAnnotation(
    assessmentId: string,
    findingId: string,
    revision: string,
    retry = false,
  ): Promise<Annotation> {
    return (
      await this.request(
        `/v1/assessments/${assessmentId}/findings/${findingId}/annotations`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ revision, retry }),
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
