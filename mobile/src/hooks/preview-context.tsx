import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  emptyConversation,
  validateQuestion,
  type ChatTurn,
  type Conversation,
} from "@/domain/chat";
import { fixtureSuggestions, previewService } from "@/api/preview-service";
import {
  previewMaskUri,
  STAGED_DELAY_MS,
  STAGED_FINDING,
  withPreviewHighlights,
} from "@/api/preview-highlights";
import { ApiError, BackendClient } from "@/api/backend-client";
import { apiConfig, apiEnabled } from "@/api/config";
import { appendPhoto } from "@/api/photo-upload";
import { newApiId } from "@/storage/device";
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
import { createPersistence } from "@/storage/persistence";
import { createPhotoStorage } from "@/storage/photos";
import { StateStore } from "@/storage/state-store";
import { historyItem, newestFirst, type HistoryItem } from "@/domain/history";

type Session = {
  scope: string;
  getToken: () => Promise<string>;
  onAuthError: (error: import("@/api/backend-client").ApiError) => void;
  registerCleanup: (cleanup: () => Promise<void>) => () => void;
};
function usePreviewState(session: Session) {
  const persistence = useRef(createPersistence(session.scope)).current;
  const { cleanPhotos, retainPhoto, removeLegacyPhotos } = useRef(
    createPhotoStorage(session.scope),
  ).current;
  const [state, setState] = useState<AppState>(emptyState);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [cleanupError, setCleanupError] = useState<string>();
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string>();
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyCursor, setHistoryCursor] = useState<string>();
  const historyActive = useRef(false);
  const historyRetryMore = useRef(false);
  const historyChanges = useRef(new Map<string, HistoryItem | null>());
  const store = useRef<StateStore | null>(null);
  if (!store.current) store.current = new StateStore(persistence, setState);
  const repository = store.current;
  const active = useRef(false);
  const client = useRef<Promise<BackendClient> | null>(null);
  const sessionActive = useRef(true);
  const backend = () => {
    if (!sessionActive.current)
      return Promise.reject(new Error("The account session has changed."));
    if (!client.current) {
      client.current = Promise.resolve(
        new BackendClient(
          {
            ...apiConfig,
            getToken: session.getToken,
            onAuthError: session.onAuthError,
          },
          appendPhoto,
        ),
      );
    }
    return client.current;
  };
  const assessmentById = (id: string) => {
    const result = repository.state.assessments.find((a) => a.id === id);
    if (!result) throw new Error("This assessment is no longer available.");
    return result;
  };
  const saveServer = async (assessment: Assessment) => {
    await repository.update((s) => ({
      ...s,
      assessments: [
        ...s.assessments.filter((a) => a.id !== assessment.id),
        {
          ...assessment,
          findings: assessment.findings.map((f) => ({
            ...f,
            localChat:
              s.assessments
                .find((a) => a.id === assessment.id)
                ?.findings.find((old) => old.id === f.id)?.localChat ??
              f.localChat,
          })),
        },
      ].sort((a, b) => a.createdAt.localeCompare(b.createdAt)),
    }));
    if (sessionActive.current) {
      historyChanges.current.set(assessment.id, historyItem(assessment));
      setHistory((items) =>
        [
          ...items.filter((a) => a.id !== assessment.id),
          historyItem(assessment),
        ].sort(newestFirst),
      );
    }
  };
  async function loadHistory(more = false) {
    if (historyActive.current || !sessionActive.current || !apiEnabled) return;
    historyActive.current = true;
    historyRetryMore.current = more;
    historyChanges.current.clear();
    setHistoryLoading(true);
    setHistoryError(undefined);
    try {
      const page = await (
        await backend()
      ).history(more ? historyCursor : undefined);
      if (!sessionActive.current) return;
      setHistory((previous) => {
        const items = more ? previous : [];
        const merged = new Map(items.map((item) => [item.id, item]));
        page.items.forEach((item) => merged.set(item.id, item));
        // Mutations that completed while this page was in flight take precedence.
        historyChanges.current.forEach((item, id) => {
          if (item) merged.set(id, item);
          else merged.delete(id);
        });
        return [...merged.values()].sort(newestFirst);
      });
      setHistoryCursor(page.nextCursor);
      setHistoryLoaded(true);
      return true;
    } catch (e) {
      if (sessionActive.current)
        setHistoryError(
          e instanceof Error ? e.message : "History could not load. Try again.",
        );
      return false;
    } finally {
      historyActive.current = false;
      if (sessionActive.current) setHistoryLoading(false);
    }
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
      if (apiEnabled) {
        await persistence.removeLegacy();
        await removeLegacyPhotos();
      }
      await repository.load();
      // Restored ready records require an explicit retry, never a model call on navigation.
      await repository.update((s) => ({
        ...s,
        assessments: s.assessments.map((a) =>
          a.status === "ready"
            ? {
                ...a,
                status: "failed",
                error:
                  "This assessment has unfinished analysis. Your input is saved. Retry when ready.",
              }
            : a,
        ),
      }));
      setReady(true);
      await cleanup();
    });
  }
  useEffect(() => {
    const remove = session.registerCleanup(async () => {
      sessionActive.current = false;
      repository.dispose();
      (await client.current)?.dispose();
      await repository.drained();
      await persistence.clear();
      await cleanPhotos([]);
    });
    void initialize();
    return () => {
      remove();
      sessionActive.current = false;
      repository.dispose();
      void client.current?.then((c) => c.dispose());
    };
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

  /** Simulated durable reply: one saved turn per change, with a growing version. */
  async function savePreviewTurn(
    aid: string,
    fid: string,
    tid: string,
    change: (turn: ChatTurn) => ChatTurn | null,
  ) {
    let result: Conversation | undefined;
    await editFinding(aid, fid, (f) => {
      const before = f.localChat?.preview ?? emptyConversation();
      const turns = before.turns.map((t) => {
        if (t.id !== tid) return t;
        const next = change(t);
        return next ? { ...next, version: (t.version ?? 0) + 1 } : t;
      });
      result = {
        ...before,
        turns,
        blocked_reason:
          turns.length >= 12
            ? "This finding has reached its 12-question limit. Your saved discussion remains available."
            : null,
      };
      return {
        ...f,
        localChat: {
          ...f.localChat,
          draft: f.localChat?.draft ?? "",
          preview: result,
        },
      };
    });
    return result;
  }
  const previewJobs = useRef(new Set<string>());
  async function runPreviewReply(aid: string, fid: string, tid: string) {
    const key = `${aid}:${fid}:${tid}`;
    if (previewJobs.current.has(key)) return;
    previewJobs.current.add(key);
    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
    try {
      await wait(700);
      const a = assessmentById(aid);
      const f = a.findings.find((f) => f.id === fid)!;
      const history = f.localChat?.preview?.turns ?? [];
      const turn = history.find((t) => t.id === tid);
      if (!turn || turn.status !== "queued" || !sessionActive.current) return;
      const fails = a.scenario === "update-error" && (turn.attempts ?? 1) === 1;
      const earlier = history.some(
        (t) => t.id !== tid && t.status === "complete",
      );
      const words =
        `Simulated guidance about “${f.title}”: ${f.recommendation} ${earlier ? "As in our earlier discussion, " : ""}${f.uncertainty} You decide whether to change this finding’s status.`.split(
          " ",
        );
      let text = "";
      let running = true;
      await savePreviewTurn(aid, fid, tid, (t) =>
        t.status === "queued"
          ? { ...t, status: "running" }
          : ((running = false), null),
      );
      for (let i = 0; running && i < words.length; i++) {
        await wait(100);
        if (!sessionActive.current) return;
        text += (i ? " " : "") + words[i];
        const failing = fails && i === 5;
        await savePreviewTurn(aid, fid, tid, (t) =>
          t.status !== "running"
            ? ((running = false), null)
            : failing
              ? {
                  ...t,
                  status: "failed",
                  partial: text,
                  error:
                    "The simulated reply was interrupted. Retry when ready.",
                  error_code: "simulated",
                }
              : { ...t, partial: text },
        );
        if (failing) return;
      }
      if (!running) return;
      await savePreviewTurn(aid, fid, tid, (t) =>
        t.status === "running"
          ? {
              ...t,
              status: "complete",
              answer: text,
              partial: "",
              finished_at: new Date().toISOString(),
            }
          : null,
      );
    } catch {
      /* Saved state stays readable; restart recovery marks it interrupted. */
    } finally {
      previewJobs.current.delete(key);
    }
  }
  return {
    apiMode: apiEnabled,
    loadRemotePhoto: async (photo: NonNullable<Photo["remote"]>) =>
      (await backend()).photoDataUrl(photo),
    state,
    history: apiEnabled
      ? [
          ...history,
          ...state.assessments
            .filter(
              (a) => !a.serverSaved && !history.some((h) => h.id === a.id),
            )
            .map(historyItem),
        ].sort(newestFirst)
      : state.assessments.map(historyItem).sort(newestFirst),
    historyLoading,
    historyError,
    historyLoaded: !apiEnabled || historyLoaded,
    historyCursor,
    loadHistory,
    retryHistory: () => loadHistory(historyRetryMore.current),
    ready,
    busy,
    error,
    cleanupError,
    initialize,
    cleanup: () => act(cleanup),
    clearError: () => setError(undefined),
    reportError: (message: string) => setError(message),
    update,
    startDraft: (replace = false) =>
      act(async () => {
        await repository.update((s) => ({
          ...s,
          draft: replace
            ? { profiles: [], scenario: s.nextScenario }
            : (s.draft ?? { profiles: [], scenario: s.nextScenario }),
        }));
        if (replace) await cleanup();
        return true;
      }),
    editDraft: (change: (draft: Draft) => Draft) =>
      update((s) => ({
        ...s,
        draft: change(s.draft ?? { profiles: [], scenario: s.nextScenario }),
      })),
    // Typing bypasses `act` so keystrokes are never dropped while another action runs.
    // The serialized store applies writes in order; failures reject without publishing.
    // A save that lands after discard or creation must not revive the draft.
    saveDraftDetails: (householdContext: string) =>
      repository.update((s) =>
        s.draft ? { ...s, draft: { ...s.draft, householdContext } } : s,
      ),
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
        // Include household-detail edits still being written.
        await repository.drained();
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
          const findings = withPreviewHighlights(
            assessment,
            await previewService.assess(assessment),
          );
          await editAssessment(id, (a) => ({
            ...a,
            status: "complete",
            title:
              a.scenario === "clear"
                ? undefined
                : a.scenario === "uncertain"
                  ? "Living room with a tall cabinet beside the sitting area"
                  : a.photo.sample === "quiet"
                    ? "Quiet Room Review"
                    : "Living Room Review",
            findings,
            ...(a.scenario === "legacy-summary"
              ? {
                  summary:
                    "Simulated older record: this sample was saved before suggestions, so its original summary is shown as written.",
                  suggestions: undefined,
                }
              : { suggestions: fixtureSuggestions(a, findings) }),
            error: undefined,
          }));
          // A simulated highlight that finishes after its siblings.
          setTimeout(() => {
            if (!sessionActive.current) return;
            void editFinding(id, STAGED_FINDING, (f) =>
              f.annotation?.state === "processing"
                ? {
                    ...f,
                    annotation: { ...f.annotation, state: "ready" },
                    annotations: [{ ...f.annotation, state: "ready" }],
                  }
                : f,
            ).catch(() => {});
          }, STAGED_DELAY_MS);
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
    saveChatDraft: async (aid: string, fid: string, draft: string) => {
      await editFinding(aid, fid, (f) => ({
        ...f,
        localChat: { ...f.localChat, draft },
      }));
    },
    loadChat: async (aid: string, fid: string): Promise<Conversation> => {
      const finding = assessmentById(aid).findings.find((f) => f.id === fid);
      if (!finding) throw new Error("This finding is no longer available.");
      if (apiEnabled) {
        const conversation = await (await backend()).chat(aid, fid);
        const outbound = finding.localChat?.outbound;
        if (
          outbound &&
          conversation.turns.some(
            (t) => t.id === outbound.id && t.question === outbound.question,
          )
        ) {
          await editFinding(aid, fid, (f) => ({
            ...f,
            localChat: {
              ...f.localChat,
              outbound: undefined,
              draft:
                f.localChat?.draft === outbound.question
                  ? ""
                  : (f.localChat?.draft ?? ""),
            },
          }));
        }
        return conversation;
      }
      return finding.localChat?.preview ?? emptyConversation();
    },
    acceptChat: async (
      aid: string,
      fid: string,
    ): Promise<{ conversation: Conversation; turnId: string }> => {
      const f = assessmentById(aid).findings.find((f) => f.id === fid)!;
      const local = f.localChat ?? { draft: "" };
      const outbound = local.outbound ?? {
        id: newApiId(),
        question: local.draft,
      };
      const invalid = validateQuestion(outbound.question);
      if (invalid) throw new Error(invalid);
      // Commit identity before the request. An ambiguous transport failure reuses it.
      await editFinding(aid, fid, (f) => ({
        ...f,
        localChat: {
          ...f.localChat,
          draft: f.localChat?.draft ?? "",
          outbound,
        },
      }));
      let conversation: Conversation;
      if (apiEnabled) {
        try {
          conversation = await (await backend()).acceptChat(aid, fid, outbound);
        } catch (e) {
          if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
            await editFinding(aid, fid, (f) => ({
              ...f,
              localChat: {
                ...f.localChat,
                draft: f.localChat?.draft ?? "",
                outbound: undefined,
              },
            }));
          }
          throw e;
        }
      } else {
        conversation = local.preview ?? emptyConversation();
        if (!conversation.turns.some((t) => t.id === outbound.id)) {
          if (conversation.turns.some((t) => t.status !== "complete"))
            throw new Error("Retry the saved question first.");
          if (conversation.turns.length >= 12)
            throw new Error("This finding has reached its 12-question limit.");
          conversation = {
            ...conversation,
            turns: [
              ...conversation.turns,
              {
                id: outbound.id,
                question: outbound.question,
                answer: null,
                status: "queued",
                error: null,
                created_at: new Date().toISOString(),
                finished_at: null,
                partial: "",
                version: 1,
                attempts: 1,
              },
            ],
          };
        }
      }
      await editFinding(aid, fid, (f) => ({
        ...f,
        localChat: {
          ...f.localChat,
          outbound: undefined,
          draft:
            f.localChat?.draft === outbound.question
              ? ""
              : (f.localChat?.draft ?? ""),
          ...(!apiEnabled ? { preview: conversation } : {}),
        },
      }));
      if (!apiEnabled) void runPreviewReply(aid, fid, outbound.id);
      return { conversation, turnId: outbound.id };
    },
    /** Explicit Retry/Continue: queues a fresh attempt; never waits for the reply. */
    generateChat: async (
      aid: string,
      fid: string,
      tid: string,
    ): Promise<Conversation> => {
      if (apiEnabled)
        return (await backend()).generateChat(aid, fid, tid, newApiId());
      const f = assessmentById(aid).findings.find((f) => f.id === fid)!;
      const before = f.localChat?.preview ?? emptyConversation();
      const turn = before.turns.find((t) => t.id === tid);
      if (!turn) throw new Error("This saved question is no longer available.");
      if (turn.status !== "failed" && turn.status !== "ready") return before;
      const conversation = await savePreviewTurn(aid, fid, tid, (t) => ({
        ...t,
        status: "queued",
        error: null,
        error_code: null,
        partial: "",
        answer: null,
        attempts: (t.attempts ?? 0) + 1,
      }));
      void runPreviewReply(aid, fid, tid);
      return conversation ?? before;
    },
    annotationClient: backend,
    /** Server masks arrive tinted by severity; preview draws simulated ones. */
    loadMask: async (
      assessment: Assessment,
      finding: Finding,
      annotationId: string,
    ) =>
      apiEnabled
        ? (await backend()).maskDataUrl(assessment.id, finding.id, annotationId)
        : previewMaskUri(assessment.photo, finding),
    loadAssessment: (id: string) =>
      act(async () => {
        const cached = repository.state.assessments.find((a) => a.id === id);
        if (apiEnabled && (!cached || cached.serverSaved)) {
          const loaded = await (await backend()).open(id, cached);
          await saveServer(loaded);
          return loaded;
        }
        if (!cached) throw new Error("This assessment is no longer available.");
        if (cached.status === "ready") {
          const recovered: Assessment = {
            ...cached,
            status: "failed",
            error: "This assessment has unfinished analysis. Retry when ready.",
          };
          await saveServer(recovered);
          return recovered;
        }
        return cached;
      }),
    refreshHistory: () =>
      act(async () => {
        if (!apiEnabled)
          throw new Error(
            "Connect to the service to refresh an account assessment.",
          );
        if (!(await loadHistory()))
          throw new Error("Could not refresh your assessment history.");
        return true;
      }),
    refreshAssessment: async (id: string) => {
      const current = assessmentById(id);
      await saveServer(await (await backend()).get(current));
    },
    deleteAssessment: (id: string) =>
      act(async () => {
        if (apiEnabled) await (await backend()).delete(id);
        await repository.update((s) => ({
          ...s,
          assessments: s.assessments.filter((a) => a.id !== id),
        }));
        historyChanges.current.set(id, null);
        setHistory((items) => items.filter((a) => a.id !== id));
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
export function PreviewProvider({
  children,
  session,
}: {
  children: ReactNode;
  session: Session;
}) {
  const value = usePreviewState(session);
  return (
    <PreviewContext.Provider value={value}>{children}</PreviewContext.Provider>
  );
}
export function usePreview() {
  const value = useContext(PreviewContext);
  if (!value) throw new Error("PreviewProvider is missing.");
  return value;
}
