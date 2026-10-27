import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { previewService } from "@/api/preview-service";
import { BackendClient } from "@/api/backend-client";
import { apiConfig, apiEnabled } from "@/api/config";
import { appendPhoto } from "@/api/photo-upload";
import { getDeviceId, newApiId } from "@/storage/device";
import {
  completeSubmission,
  createAssessment,
  emptyState,
  makeId,
  retainedPhotos,
  type AppState,
  type Assessment,
  type Draft,
  type Finding,
  type FindingStatus,
  type Photo,
  type Submission,
} from "@/domain/model";
import { persistence } from "@/storage/persistence";
import { cleanPhotos, retainPhoto } from "@/storage/photos";
import { StateStore } from "@/storage/state-store";

function usePreviewState() {
  const [state, setState] = useState<AppState>(emptyState);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [cleanupError, setCleanupError] = useState<string>();
  const store = useRef<StateStore | null>(null);
  if (!store.current) store.current = new StateStore(persistence, setState);
  const repository = store.current;
  const active = useRef(false);
  const client = useRef<Promise<BackendClient> | null>(null);
  const backend = () => {
    if (!client.current) {
      client.current = getDeviceId()
        .then(
          (deviceId) =>
            new BackendClient({ ...apiConfig, deviceId }, appendPhoto),
        )
        .catch((error) => {
          client.current = null;
          throw error;
        });
    }
    return client.current;
  };
  const assessmentById = (id: string) => {
    const result = repository.state.assessments.find((a) => a.id === id);
    if (!result) throw new Error("This assessment is no longer available.");
    return result;
  };
  const saveServer = (assessment: Assessment) =>
    repository.update((s) => ({
      ...s,
      assessments: [
        ...s.assessments.filter((a) => a.id !== assessment.id),
        assessment,
      ].sort((a, b) => a.createdAt.localeCompare(b.createdAt)),
    }));
  async function refreshLatest() {
    const latest = await (await backend()).latest(repository.state.assessments);
    await repository.update((s) => ({
      ...s,
      assessments: [
        ...s.assessments.filter((a) => !a.serverSaved && a.id !== latest?.id),
        ...(latest ? [latest] : []),
      ].sort((a, b) => a.createdAt.localeCompare(b.createdAt)),
    }));
  }
  async function retainFailure(
    id: string,
    error: unknown,
    findingId?: string,
    submissionId?: string,
  ) {
    let assessment = assessmentById(id);
    try {
      assessment = await (await backend()).get(assessment);
    } catch {
      /* Keep local evidence if the network is unavailable. */
    }
    const message =
      error instanceof Error
        ? error.message
        : "The request could not finish. Retry when ready.";
    if (findingId && submissionId) {
      assessment = {
        ...assessment,
        findings: assessment.findings.map((f) =>
          f.id !== findingId
            ? f
            : {
                ...f,
                submissions: f.submissions.map((s) =>
                  s.id !== submissionId || s.status === "complete"
                    ? s
                    : {
                        ...s,
                        status: "failed",
                        error: message,
                      },
                ),
              },
        ),
      };
    } else if (assessment.status !== "complete") {
      assessment = { ...assessment, status: "failed", error: message };
    }
    await saveServer(assessment);
  }

  async function act<T>(work: () => Promise<T>): Promise<T | undefined> {
    if (active.current) return undefined;
    active.current = true;
    setBusy(true);
    setError(undefined);
    try {
      return await work();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "The change could not be saved. Please try again.",
      );
      return undefined;
    } finally {
      active.current = false;
      setBusy(false);
    }
  }
  async function cleanup() {
    try {
      await cleanPhotos(retainedPhotos(repository.state));
      setCleanupError(undefined);
    } catch {
      setCleanupError(
        "Some unused photos could not be removed from this device. Retry cleanup.",
      );
    }
  }
  async function initialize() {
    await act(async () => {
      await repository.load();
      if (apiEnabled) await refreshLatest();
      setReady(true);
      await cleanup();
    });
  }
  useEffect(() => {
    void initialize();
  }, []);

  const update = (change: (state: AppState) => AppState) =>
    act(async () => {
      await repository.update(change);
      return true;
    });
  const editAssessment = (id: string, change: (a: Assessment) => Assessment) =>
    repository.update((s) => ({
      ...s,
      assessments: s.assessments.map((a) => (a.id === id ? change(a) : a)),
    }));
  const editFinding = (
    assessmentId: string,
    findingId: string,
    change: (f: Finding) => Finding,
  ) =>
    editAssessment(assessmentId, (a) => ({
      ...a,
      findings: a.findings.map((f) => (f.id === findingId ? change(f) : f)),
    }));

  return {
    apiMode: apiEnabled,
    loadRemotePhoto: async (photo: NonNullable<Photo["remote"]>) =>
      (await backend()).photoDataUrl(photo),
    state,
    ready,
    busy,
    error,
    cleanupError,
    initialize,
    cleanup: () => act(cleanup),
    clearError: () => setError(undefined),
    reportError: (message: string) => setError(message),
    update,
    startDraft: () =>
      update((s) => ({
        ...s,
        draft: s.draft ?? { profiles: [], scenario: s.nextScenario },
      })),
    editDraft: (change: (draft: Draft) => Draft) =>
      update((s) => ({
        ...s,
        draft: change(s.draft ?? { profiles: [], scenario: s.nextScenario }),
      })),
    choosePhoto: (photo: Photo) =>
      act(async () => {
        const retained = await retainPhoto(photo);
        await repository.update((s) => ({
          ...s,
          draft: {
            ...(s.draft ?? { profiles: [], scenario: s.nextScenario }),
            photo: retained,
          },
        }));
        await cleanup();
        return true;
      }),
    discardDraft: () =>
      act(async () => {
        await repository.update((s) => ({ ...s, draft: null }));
        await cleanup();
        return true;
      }),
    create: () =>
      act(async () => {
        if (!repository.state.draft)
          throw new Error("Choose a photo to start an assessment.");
        const assessment = createAssessment(repository.state.draft);
        if (apiEnabled) assessment.id = newApiId();
        await repository.update((s) => ({
          ...s,
          draft: null,
          assessments: [...s.assessments, assessment],
        }));
        return assessment;
      }),
    runAnalysis: (id: string) =>
      act(async () => {
        let assessment = repository.state.assessments.find((a) => a.id === id);
        if (!assessment || assessment.status === "complete") return;
        await editAssessment(id, (a) => ({
          ...a,
          status: "running",
          attempts: a.attempts + 1,
          error: undefined,
        }));
        assessment = repository.state.assessments.find((a) => a.id === id)!;
        try {
          if (apiEnabled) {
            const api = await backend();
            const uploaded = await api.upload(assessment);
            await saveServer({ ...uploaded, status: "running" });
            await saveServer(await api.analyze(uploaded));
            return;
          }
          const findings = await previewService.assess(assessment);
          await editAssessment(id, (a) => ({
            ...a,
            status: "complete",
            findings,
            error: undefined,
          }));
        } catch (e) {
          if (apiEnabled) {
            await retainFailure(id, e);
            return;
          }
          await editAssessment(id, (a) => ({
            ...a,
            status: "failed",
            error:
              e instanceof Error ? e.message : "The preview could not finish.",
          }));
        }
      }),
    changeStatus: (
      assessmentId: string,
      findingId: string,
      status: FindingStatus,
      note?: string,
    ) =>
      act(async () => {
        if (apiEnabled) {
          await saveServer(
            await (
              await backend()
            ).patch(assessmentById(assessmentId), findingId, status, note),
          );
          return true;
        }
        await editFinding(assessmentId, findingId, (f) => ({
          ...f,
          status,
          note: status === "dismissed" ? note || "" : "",
        }));
        return true;
      }),
    skip: (assessmentId: string, findingId: string) =>
      act(async () => {
        if (apiEnabled) {
          await saveServer(
            await (
              await backend()
            ).skip(assessmentById(assessmentId), findingId),
          );
          return true;
        }
        await editFinding(assessmentId, findingId, (f) => {
          if (
            !f.followUp ||
            f.followUp.state !== "available" ||
            f.submissions.some(
              (s) => s.kind === "follow-up" && s.status !== "complete",
            )
          )
            return f;
          return { ...f, followUp: { ...f.followUp, state: "skipped" } };
        });
        return true;
      }),
    saveInput: (
      assessmentId: string,
      findingId: string,
      kind: Submission["kind"],
      input: { text?: string; photo?: Photo },
    ) =>
      act(async () => {
        const previous = assessmentById(assessmentId)
          .findings.find((f) => f.id === findingId)
          ?.submissions.find((s) => s.kind === kind && s.status !== "complete");
        if (apiEnabled && previous?.frozen) {
          if (
            (!input.photo || input.photo.id === previous.photo?.id) &&
            (input.text === undefined || input.text === previous.text)
          )
            return true;
          throw new Error(
            "Submitted evidence is saved and cannot be edited. Retry the saved check.",
          );
        }
        const photo = input.photo ? await retainPhoto(input.photo) : undefined;
        await editFinding(assessmentId, findingId, (f) => {
          const pending = f.submissions.find(
            (s) => s.kind === kind && s.status !== "complete",
          );
          if (pending?.status === "running")
            throw new Error("Wait for the current check to finish.");
          if (kind === "follow-up" && f.followUp?.state !== "available")
            throw new Error(
              "This follow-up has already been handled. You can request a photo review.",
            );
          const submission: Submission = {
            ...(pending ?? {
              id: apiEnabled ? newApiId() : makeId(),
              kind,
              status: "ready",
              attempts: 0,
              text: "",
            }),
            ...input,
            ...(photo ? { photo } : {}),
          };
          return {
            ...f,
            submissions: pending
              ? f.submissions.map((s) => (s.id === pending.id ? submission : s))
              : [...f.submissions, submission],
          };
        });
        await cleanup();
        return true;
      }),
    runCheck: (
      assessmentId: string,
      findingId: string,
      kind: Submission["kind"],
    ) =>
      act(async () => {
        let assessment = repository.state.assessments.find(
          (a) => a.id === assessmentId,
        )!;
        let finding = assessment.findings.find((f) => f.id === findingId)!;
        const input = finding.submissions.find(
          (s) => s.kind === kind && s.status !== "complete",
        );
        if (!input)
          throw new Error("Add your answer or photo before submitting.");
        if (
          kind === "review" || finding.followUp?.kind === "photo"
            ? !input.photo
            : !input.text.trim()
        )
          throw new Error("Add the requested evidence before submitting.");
        await editFinding(assessmentId, findingId, (f) => ({
          ...f,
          submissions: f.submissions.map((s) =>
            s.id === input.id
              ? {
                  ...s,
                  status: "running",
                  attempts: s.attempts + 1,
                  error: undefined,
                  frozen: apiEnabled ? true : s.frozen,
                }
              : s,
          ),
        }));
        assessment = repository.state.assessments.find(
          (a) => a.id === assessmentId,
        )!;
        finding = assessment.findings.find((f) => f.id === findingId)!;
        const submission = finding.submissions.find((s) => s.id === input.id)!;
        try {
          if (apiEnabled) {
            const api = await backend();
            const uploaded = await api.uploadSubmission(
              assessment,
              finding,
              submission,
            );
            await saveServer({
              ...uploaded,
              findings: uploaded.findings.map((f) =>
                f.id !== findingId
                  ? f
                  : {
                      ...f,
                      submissions: f.submissions.map((s) =>
                        s.id !== submission.id
                          ? s
                          : {
                              ...s,
                              status: "running",
                              attempts: submission.attempts,
                              error: undefined,
                            },
                      ),
                    },
              ),
            });
            await saveServer(
              await api.check(uploaded, findingId, submission.id),
            );
            return;
          }
          const feedback = await previewService.check(
            assessment,
            finding,
            submission,
          );
          await editFinding(assessmentId, findingId, (f) =>
            completeSubmission(f, input.id, feedback),
          );
        } catch (e) {
          if (apiEnabled) {
            await retainFailure(assessmentId, e, findingId, submission.id);
            return;
          }
          await editFinding(assessmentId, findingId, (f) => ({
            ...f,
            submissions: f.submissions.map((s) =>
              s.id === input.id
                ? {
                    ...s,
                    status: "failed",
                    error:
                      e instanceof Error
                        ? e.message
                        : "The check could not finish.",
                  }
                : s,
            ),
          }));
        }
      }),
    deleteAssessment: (id: string) =>
      act(async () => {
        if (apiEnabled) await (await backend()).delete(id);
        await repository.update((s) => ({
          ...s,
          assessments: s.assessments.filter((a) => a.id !== id),
        }));
        if (apiEnabled) await refreshLatest();
        await cleanup();
        return true;
      }),
    reset: () =>
      act(async () => {
        if (apiEnabled)
          throw new Error(
            "Preview reset is unavailable while connected to the service.",
          );
        await repository.update(emptyState);
        await cleanup();
        return true;
      }),
  };
}
type PreviewContextValue = ReturnType<typeof usePreviewState>;
const PreviewContext = createContext<PreviewContextValue | null>(null);
export function PreviewProvider({ children }: { children: ReactNode }) {
  const value = usePreviewState();
  return (
    <PreviewContext.Provider value={value}>{children}</PreviewContext.Provider>
  );
}
export function usePreview() {
  const value = useContext(PreviewContext);
  if (!value) throw new Error("PreviewProvider is missing.");
  return value;
}
