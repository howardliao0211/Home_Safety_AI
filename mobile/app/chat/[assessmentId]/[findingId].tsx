import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentRef,
} from "react";
import {
  AccessibilityInfo,
  ActivityIndicator,
  AppState,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useNavigation, usePreventRemove } from "expo-router/react-navigation";
import { useHeaderHeight } from "expo-router/react-navigation";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AssessmentGate } from "@/components/assessment-gate";
import { Button, Copy, Notice, styles } from "@/components/ui";
import { colors, tokens } from "@/components/theme";
import { usePreview } from "@/hooks/preview-context";
import {
  isActive,
  isIncomplete,
  MAX_CHAT_QUESTION,
  mergeConversation,
  observeJob,
  validateQuestion,
  type Conversation,
} from "@/domain/chat";
import { ApiError } from "@/api/backend-client";

// With ~200 ms backend publishing, keeps provider-to-screen delivery near 500 ms.
const POLL_MS = 250;

export default function ChatRoute() {
  const { assessmentId, findingId } = useLocalSearchParams<{
    assessmentId: string;
    findingId: string;
  }>();
  return (
    <AssessmentGate id={assessmentId}>
      <Chat
        key={`${assessmentId}:${findingId}`}
        aid={assessmentId}
        fid={findingId}
      />
    </AssessmentGate>
  );
}

function Chat({ aid, fid }: { aid: string; fid: string }) {
  const context = usePreview();
  const latest = useRef(context);
  latest.current = context;
  const finding = context.state.assessments
    .find((a) => a.id === aid)
    ?.findings.find((f) => f.id === fid);
  const [conversation, setConversation] = useState<Conversation>();
  const [draft, setDraft] = useState(finding?.localChat?.draft ?? "");
  const draftRef = useRef(draft);
  const saveVersion = useRef(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [draftError, setDraftError] = useState("");
  const [unavailable, setUnavailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const activeRequest = useRef(false);
  const mounted = useRef(true);
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);
  const atBottom = useRef(true);
  const [newMessages, setNewMessages] = useState(false);
  const insets = useSafeAreaInsets();
  const headerHeight = useHeaderHeight();
  const navigation = useNavigation();
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  function message(e: unknown) {
    return e instanceof Error ? e.message : "Chat could not load. Try again.";
  }
  function checkUnavailable(e: unknown) {
    if (e instanceof ApiError && (e.status === 404 || e.code === "deleting"))
      setUnavailable(true);
  }
  // `observing`: a background progress read. It neither toggles loading nor
  // clears a shown error before succeeding, so streaming text never flickers.
  const load = useCallback(
    async (observing = false) => {
      if (!mounted.current) return;
      if (!observing) {
        setLoading(true);
        setLoadError("");
      }
      try {
        const outbound = latest.current.state.assessments
          .find((a) => a.id === aid)
          ?.findings.find((f) => f.id === fid)?.localChat?.outbound;
        const result = await latest.current.loadChat(aid, fid);
        if (mounted.current) {
          if (observing) setLoadError("");
          setConversation((current) => mergeConversation(current, result));
          if (
            outbound &&
            result.turns.some((t) => t.id === outbound.id) &&
            draftRef.current === outbound.question
          ) {
            draftRef.current = "";
            setDraft("");
          }
        }
        return result;
      } catch (e) {
        if (mounted.current) {
          setLoadError(message(e));
          checkUnavailable(e);
        }
      } finally {
        if (mounted.current && !observing) setLoading(false);
      }
    },
    [aid, fid],
  );
  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );
  const pending = conversation?.turns.find((t) => t.status !== "complete");
  const active = !!pending && isActive(pending);
  // Observe the saved job while it is active, on this or a reopened screen.
  // Reads never start generation; the backend job continues independently.
  useFocusEffect(
    useCallback(() => {
      if (!active) return;
      let stop =
        AppState.currentState === "active"
          ? observeJob(() => load(true), POLL_MS)
          : undefined;
      const listener = AppState.addEventListener("change", (state) => {
        stop?.();
        stop =
          state === "active"
            ? observeJob(() => load(true), POLL_MS)
            : undefined;
      });
      return () => {
        stop?.();
        listener.remove();
      };
    }, [active, load]),
  );
  // Phase changes only; the transcript is never re-read on each fragment.
  const announcement =
    draftError ||
    error ||
    loadError ||
    (pending?.status === "queued"
      ? "Reply queued."
      : pending?.status === "running"
        ? "Writing a reply…"
        : pending?.status === "failed"
          ? `${isIncomplete(pending) ? "Incomplete response. " : ""}${pending.error ?? ""}`
          : conversation?.turns.at(-1)?.status === "complete"
            ? "Reply available."
            : "");
  useEffect(() => {
    if (announcement && Platform.OS === "ios")
      AccessibilityInfo.announceForAccessibility(announcement);
  }, [announcement]);
  async function persistDraft(text: string) {
    const version = ++saveVersion.current;
    try {
      await latest.current.saveChatDraft(aid, fid, text);
      if (mounted.current && version === saveVersion.current) setDraftError("");
    } catch (e) {
      if (mounted.current && version === saveVersion.current)
        setDraftError(message(e));
      throw e;
    }
  }
  usePreventRemove(draft !== (finding?.localChat?.draft ?? ""), ({ data }) => {
    void persistDraft(draftRef.current)
      .then(() => navigation.dispatch(data.action))
      .catch(() => {});
  });
  function edit(text: string) {
    draftRef.current = text;
    setDraft(text);
    setError("");
    void persistDraft(text).catch(() => {});
  }
  async function perform(turnId?: string) {
    if (activeRequest.current) return;
    if (!turnId && !finding?.localChat?.outbound) {
      const invalid = validateQuestion(draftRef.current);
      if (invalid) {
        setError(invalid);
        return;
      }
    }
    activeRequest.current = true;
    setBusy(true);
    setError("");
    try {
      if (!turnId) {
        const sent = finding?.localChat?.outbound?.question ?? draftRef.current;
        await persistDraft(draftRef.current);
        // Acceptance saves the question and queues its reply job.
        const accepted = await latest.current.acceptChat(aid, fid);
        if (!mounted.current) return;
        setConversation((c) => mergeConversation(c, accepted.conversation));
        if (draftRef.current === sent) {
          draftRef.current = "";
          setDraft("");
        }
        return;
      }
      // Explicit Retry/Continue queues a fresh attempt for the same question.
      const result = await latest.current.generateChat(aid, fid, turnId);
      if (mounted.current) setConversation((c) => mergeConversation(c, result));
    } catch (e) {
      if (mounted.current) {
        setError(message(e));
        checkUnavailable(e);
      }
      // Read after ambiguous responses to reconcile accepted/completed operations.
      const reconciled = await load();
      if (mounted.current && reconciled?.turns.at(-1)?.status === "complete")
        setError("");
    } finally {
      activeRequest.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  if (!finding || unavailable)
    return (
      <View style={styles.content}>
        <Copy kind="heading">Finding unavailable</Copy>
        <Copy>
          This finding may have been deleted or is no longer accessible.
        </Copy>
        <Button label="Back to Home" onPress={() => router.dismissTo("/")} />
      </View>
    );
  const outbound = finding.localChat?.outbound;
  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === "ios" ? "padding" : "height"}
      keyboardVerticalOffset={headerHeight}
    >
      <View
        style={{
          flex: 1,
          width: "100%",
          maxWidth: tokens.maxWidth,
          alignSelf: "center",
        }}
      >
        <ScrollView
          ref={scroll}
          style={{ flex: 1 }}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={[styles.content, { paddingBottom: 20 }]}
          onScroll={({ nativeEvent: e }) => {
            atBottom.current =
              e.contentSize.height -
                e.layoutMeasurement.height -
                e.contentOffset.y <
              80;
            if (atBottom.current) setNewMessages(false);
          }}
          scrollEventThrottle={100}
          onContentSizeChange={() => {
            if (atBottom.current)
              scroll.current?.scrollToEnd({ animated: false });
            else setNewMessages(true);
          }}
        >
          <Copy kind="heading" accessibilityRole="header">
            {finding.title}
          </Copy>
          {loading && !conversation && (
            <ActivityIndicator
              color={colors.accent}
              accessibilityLabel="Loading chat"
            />
          )}
          {!!loadError && (
            <Notice title="Chat could not load" tone="error">
              <Copy>{loadError}</Copy>
              <Button label="Retry loading chat" onPress={() => void load()} />
            </Notice>
          )}
          {conversation?.turns.length === 0 && (
            <Copy>
              Ask questions about this finding. Chat offers guidance; you decide
              what to do and when to change its status.
            </Copy>
          )}
          {conversation?.turns.map((t) => (
            <View key={t.id} style={{ gap: 16 }}>
              <View
                style={{
                  backgroundColor: colors.soft,
                  padding: 16,
                  borderRadius: tokens.controlRadius,
                  gap: 8,
                }}
              >
                <Copy kind="eyebrow">YOU</Copy>
                <Copy testID="chat-user-message">{t.question}</Copy>
              </View>
              {t.status === "complete" && t.answer && (
                <View style={{ padding: 16, gap: 8 }}>
                  <Copy kind="eyebrow">ASSISTANT</Copy>
                  <Copy testID="chat-assistant-message">{t.answer}</Copy>
                </View>
              )}
              {isActive(t) && (
                <View style={{ padding: 16, gap: 8 }}>
                  <View style={styles.row}>
                    <Copy kind="eyebrow">ASSISTANT</Copy>
                    <ActivityIndicator
                      size="small"
                      color={colors.accent}
                      accessible={false}
                    />
                    <Copy kind="small">
                      {t.status === "queued" ? "Waiting to start…" : "Writing…"}
                    </Copy>
                  </View>
                  {!!t.partial && (
                    <Copy testID="chat-assistant-message">{t.partial}</Copy>
                  )}
                </View>
              )}
              {isIncomplete(t) && (
                <View
                  style={{
                    padding: 16,
                    gap: 8,
                    borderWidth: 1,
                    borderStyle: "dashed",
                    borderColor: colors.line,
                    borderRadius: tokens.controlRadius,
                  }}
                >
                  <Copy kind="eyebrow" style={{ color: colors.danger }}>
                    INCOMPLETE RESPONSE
                  </Copy>
                  <Copy style={{ color: colors.muted }}>{t.partial}</Copy>
                </View>
              )}
              {t.status === "failed" && (
                <Notice
                  title="Reply could not finish"
                  tone="error"
                  announce={false}
                >
                  <Copy>{t.error}</Copy>
                </Notice>
              )}
              {t.status === "ready" && (
                <Notice title="Reply not started">
                  <Copy>
                    This saved question has no reply yet. Continue when you’re
                    ready.
                  </Copy>
                </Notice>
              )}
            </View>
          ))}
          {outbound &&
            !conversation?.turns.some((t) => t.id === outbound.id) && (
              <Notice title="Submission not confirmed">
                <Copy>{outbound.question}</Copy>
                <Copy kind="small">
                  Retry sends this same question with its saved identity. Your
                  new draft stays saved.
                </Copy>
              </Notice>
            )}
        </ScrollView>
        <ScrollView
          style={{ flexGrow: 0, flexShrink: 0, maxHeight: "60%" }}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{
            paddingHorizontal: 20,
            paddingTop: 8,
            paddingBottom: Math.max(insets.bottom, 12),
            gap: 8,
            backgroundColor: colors.background,
            borderTopWidth: 1,
            borderColor: colors.line,
          }}
        >
          {newMessages && (
            <Button
              label="Go to newest message"
              variant="text"
              onPress={() => {
                atBottom.current = true;
                scroll.current?.scrollToEnd({ animated: false });
                setNewMessages(false);
              }}
            />
          )}
          <Copy kind="small" accessibilityLiveRegion="polite">
            {announcement}
          </Copy>
          {conversation?.blocked_reason && (
            <Copy kind="small">{conversation.blocked_reason}</Copy>
          )}
          {conversation?.retry_blocked_reason &&
            conversation.retry_blocked_reason !==
              conversation.blocked_reason && (
              <Copy kind="small">{conversation.retry_blocked_reason}</Copy>
            )}
          {pending &&
            !isActive(pending) &&
            !conversation?.retry_blocked_reason && (
              <Button
                label={
                  pending.status === "ready" ? "Continue reply" : "Retry reply"
                }
                variant="secondary"
                disabled={busy || !!loadError}
                onPress={() => void perform(pending.id)}
              />
            )}
          {outbound && !pending && (
            <Button
              label="Retry send"
              variant="secondary"
              disabled={busy || !!loadError || !!conversation?.blocked_reason}
              onPress={() => void perform()}
            />
          )}
          <Copy kind="small">Your question</Copy>
          <TextInput
            accessibilityLabel="Your question"
            placeholder="Ask about this finding…"
            placeholderTextColor={colors.muted}
            multiline
            value={draft}
            onChangeText={edit}
            style={[styles.input, { minHeight: 64, maxHeight: 140 }]}
          />
          <Copy kind="small">
            {draft.length.toLocaleString()} /{" "}
            {MAX_CHAT_QUESTION.toLocaleString()} characters
            {draftError ? " · Draft could not save" : ""}
          </Copy>
          <Button
            label="Send"
            disabled={
              busy ||
              loading ||
              !!loadError ||
              !conversation ||
              !!pending ||
              !!outbound ||
              !!conversation.blocked_reason
            }
            onPress={() => void perform()}
          />
          <Button
            label="Back to finding"
            variant="text"
            onPress={() =>
              router.dismissTo({
                pathname: "/finding/[assessmentId]/[findingId]",
                params: { assessmentId: aid, findingId: fid },
              })
            }
          />
        </ScrollView>
      </View>
    </KeyboardAvoidingView>
  );
}
