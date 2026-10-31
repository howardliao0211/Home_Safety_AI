import { apiEnabled } from "@/api/config";
import { useEffect, useRef, useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import { Redirect, router } from "expo-router";
import { useNavigation, usePreventRemove } from "expo-router/react-navigation";
import {
  householdDetailsError,
  householdDetailsLength,
  isDraftDirty,
  MAX_HOUSEHOLD_DETAILS,
  profiles,
} from "@/domain/model";
import { usePreview } from "@/hooks/preview-context";
import { PhotoInput } from "@/components/photo-input";
import { Icon } from "@/components/icon";
import {
  Button,
  ConfirmDialog,
  Copy,
  Screen,
  Section,
  Step,
  styles,
} from "@/components/ui";
import { colors } from "@/components/theme";

export default function CaptureScreen() {
  const {
    state,
    busy,
    editDraft,
    choosePhoto,
    discardDraft,
    saveDraftDetails,
  } = usePreview();
  const navigation = useNavigation();
  const [leave, setLeave] = useState<(() => void) | null>(null);
  const draft = state.draft;
  // Local text is the source of truth while typing; storage may lag or fail.
  const [details, setDetails] = useState(draft?.householdContext ?? "");
  const detailsRef = useRef(details);
  const saveVersion = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  // A discarded or submitted draft leaves this screen; a later draft starts blank.
  useEffect(() => {
    if (draft) return;
    detailsRef.current = "";
    setDetails("");
  }, [draft]);
  const [saveError, setSaveError] = useState("");
  const detailsError = householdDetailsError(details);
  const dirty =
    !!draft && isDraftDirty({ ...draft, householdContext: details });
  async function persistDetails(text: string) {
    const version = ++saveVersion.current;
    try {
      await saveDraftDetails(text);
      if (mounted.current && version === saveVersion.current) setSaveError("");
      return true;
    } catch (e) {
      if (mounted.current && version === saveVersion.current)
        setSaveError(
          e instanceof Error
            ? `Household details could not be saved. ${e.message}`
            : "Household details could not be saved. Try again.",
        );
      return false;
    }
  }
  function editDetails(text: string) {
    detailsRef.current = text;
    setDetails(text);
    void persistDetails(text);
  }
  async function review() {
    if (householdDetailsError(detailsRef.current)) return;
    if (await persistDetails(detailsRef.current)) router.push("/confirm");
  }
  usePreventRemove(dirty, ({ data }) =>
    setLeave(() => () => navigation.dispatch(data.action)),
  );
  if (!draft) return <Redirect href="/" />;
  return (
    <Screen>
      <Step number={1} label="Your room" />
      <View style={{ gap: 10 }}>
        <Copy kind="title" accessibilityRole="header">
          Let’s start with{"\n"}a room photo.
        </Copy>
        <Copy style={{ color: colors.muted }}>
          A familiar space, seen with fresh eyes.
        </Copy>
      </View>
      <PhotoInput
        photo={draft.photo}
        onChange={choosePhoto}
        denyCamera={draft.scenario === "permission-denied"}
      />
      <Section title="Who are you looking out for?">
        <Copy kind="small">
          Choose any groups that apply, and add details below if you’d like.
          Both are optional.
        </Copy>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10 }}>
          {profiles.map((profile) => {
            const selected = draft.profiles.includes(profile);
            return (
              <Pressable
                key={profile}
                accessibilityRole="checkbox"
                accessibilityLabel={profile}
                aria-checked={selected}
                aria-disabled={busy}
                accessibilityState={{ checked: selected, disabled: busy }}
                disabled={busy}
                onPress={() =>
                  void editDraft((d) => ({
                    ...d,
                    profiles: d.profiles.includes(profile)
                      ? d.profiles.filter((p) => p !== profile)
                      : [...d.profiles, profile],
                  }))
                }
                style={({ pressed }) => ({
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 8,
                  minHeight: 50,
                  paddingHorizontal: 16,
                  paddingVertical: 12,
                  backgroundColor: selected ? colors.soft : colors.surface,
                  borderWidth: 1,
                  borderColor: selected ? colors.accent : colors.line,
                  borderRadius: 12,
                  opacity: pressed ? 0.7 : 1,
                })}
              >
                {selected && <Icon name="check" size={17} />}
                <Copy
                  style={{ fontSize: 15, fontWeight: selected ? "600" : "400" }}
                >
                  {profile}
                </Copy>
              </Pressable>
            );
          })}
        </View>
        <View style={{ gap: 8 }}>
          <Copy kind="small" style={{ fontWeight: "600", color: colors.ink }}>
            Household details (optional)
          </Copy>
          <TextInput
            accessibilityLabel="Household details (optional)"
            accessibilityHint="Ages, mobility needs, or pets in your household."
            aria-invalid={!!detailsError}
            placeholder="For example, a 2-year-old, an adult who uses a walker, or two indoor cats."
            placeholderTextColor={colors.muted}
            multiline
            value={details}
            onChangeText={editDetails}
            style={[
              styles.input,
              { maxHeight: 240 },
              detailsError
                ? { borderColor: colors.danger, borderWidth: 2 }
                : null,
            ]}
          />
          <Copy kind="small">
            {householdDetailsLength(details).toLocaleString("en-AU")} /{" "}
            {MAX_HOUSEHOLD_DETAILS.toLocaleString("en-AU")} characters
          </Copy>
          {!!detailsError && (
            <Copy
              kind="small"
              accessibilityRole="alert"
              accessibilityLiveRegion="polite"
              style={{ color: colors.danger, fontWeight: "600" }}
            >
              {detailsError}
            </Copy>
          )}
          {!!saveError && (
            <Copy
              kind="small"
              accessibilityRole="alert"
              accessibilityLiveRegion="polite"
              style={{ color: colors.danger }}
            >
              {saveError}
            </Copy>
          )}
        </View>
      </Section>
      <View style={{ gap: 8 }}>
        <Button
          label="Review photo"
          icon="arrow"
          disabled={!draft.photo || !!detailsError}
          onPress={() => void review()}
        />
        {!draft.photo && (
          <Copy kind="small">Choose a photo or sample to continue.</Copy>
        )}
        <Button
          label="Cancel new assessment"
          variant="text"
          onPress={() => {
            if (dirty) setLeave(() => () => router.replace("/"));
            else
              void discardDraft().then((ok) => {
                if (ok) router.replace("/");
              });
          }}
        />
      </View>
      <ConfirmDialog
        visible={!!leave}
        title="Discard this submission?"
        message={
          apiEnabled
            ? "This unsent draft, its photo and household details will be removed. Earlier assessments remain saved."
            : "This draft, its photo and household details will be removed. Your earlier assessments will stay on this device."
        }
        confirm="Discard draft"
        onCancel={() => setLeave(null)}
        onConfirm={() => {
          void discardDraft().then((ok) => {
            if (ok) {
              const go = leave;
              setLeave(null);
              go?.();
            }
          });
        }}
      />
    </Screen>
  );
}
