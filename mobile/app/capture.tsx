import { useState } from "react";
import { Pressable, View } from "react-native";
import { Redirect, router } from "expo-router";
import { useNavigation, usePreventRemove } from "expo-router/react-navigation";
import { profiles } from "@/domain/model";
import { usePreview } from "@/hooks/preview-context";
import { PhotoInput } from "@/components/photo-input";
import { Icon } from "@/components/icon";
import {
  Button,
  ConfirmDialog,
  Copy,
  Disclaimer,
  PreviewNotice,
  Screen,
  Section,
  Step,
} from "@/components/ui";
import { colors } from "@/components/theme";

export default function CaptureScreen() {
  const { state, busy, editDraft, choosePhoto, discardDraft } = usePreview();
  const navigation = useNavigation();
  const [leave, setLeave] = useState<(() => void) | null>(null);
  const draft = state.draft;
  const dirty = !!draft?.photo || !!draft?.profiles.length;
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
          Optional. Choose everyone who lives here, or leave blank for a general
          assessment.
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
      </Section>
      <View style={{ gap: 8 }}>
        <Button
          label="Review photo"
          icon="arrow"
          disabled={!draft.photo}
          onPress={() => router.push("/confirm")}
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
      <PreviewNotice />
      <Disclaimer />
      <ConfirmDialog
        visible={!!leave}
        title="Discard this submission?"
        message="This draft and its photo will be removed. Your earlier assessments will stay on this device."
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
