import { useState } from "react";
import { Pressable, View } from "react-native";
import { Redirect, router } from "expo-router";
import { scenarios } from "@/domain/model";
import { usePreview } from "@/hooks/preview-context";
import { Icon } from "@/components/icon";
import { Button, ConfirmDialog, Copy, Notice, Screen } from "@/components/ui";
import { colors } from "@/components/theme";

export default function PreviewTools() {
  const { state, busy, update, startDraft, reset, discardDraft } = usePreview();
  const [resetting, setResetting] = useState(false);
  const [replacing, setReplacing] = useState(false);
  if (!__DEV__) return <Redirect href="/" />;
  async function freshDemo() {
    if (state.draft) {
      setReplacing(true);
      return;
    }
    if (await startDraft()) router.push("/capture");
  }
  return (
    <Screen>
      <Copy kind="eyebrow">DEVELOPMENT ONLY</Copy>
      <Copy kind="title" accessibilityRole="header">
        Explore the product states.
      </Copy>
      <Copy>
        Choose the scenario for your next assessment. Existing assessments keep
        their original scenario and data.
      </Copy>
      <View style={{ gap: 12 }}>
        {scenarios.map((scenario) => (
          <Pressable
            key={scenario.id}
            accessibilityRole="radio"
            accessibilityLabel={scenario.title}
            aria-checked={state.nextScenario === scenario.id}
            aria-disabled={busy}
            accessibilityState={{
              checked: state.nextScenario === scenario.id,
              disabled: busy,
            }}
            disabled={busy}
            onPress={() =>
              void update((s) => ({ ...s, nextScenario: scenario.id }))
            }
            style={({ pressed }) => ({
              borderWidth: 1,
              borderColor:
                state.nextScenario === scenario.id
                  ? colors.accent
                  : colors.line,
              padding: 18,
              borderRadius: 14,
              gap: 6,
              backgroundColor:
                state.nextScenario === scenario.id ? colors.soft : "#fff",
              opacity: pressed ? 0.7 : 1,
            })}
          >
            <View
              style={{ flexDirection: "row", gap: 12, alignItems: "center" }}
            >
              <Copy kind="heading" style={{ flex: 1 }}>
                {scenario.title}
              </Copy>
              {state.nextScenario === scenario.id && <Icon name="check" />}
            </View>
            <Copy kind="small">{scenario.description}</Copy>
          </Pressable>
        ))}
      </View>
      <Button
        label="Start fresh demo"
        icon="plus"
        onPress={() => void freshDemo()}
      />
      <Notice title="Product behavior, not model evaluation">
        <Copy>
          Sample findings are fixed and do not analyse the photo. Use these
          scenarios to review navigation, checklist state, and recovery.
        </Copy>
      </Notice>
      <Button
        label="Reset all preview data"
        icon="trash"
        variant="danger"
        onPress={() => setResetting(true)}
      />
      <ConfirmDialog
        visible={resetting}
        title="Reset the whole preview?"
        message="All local assessments, drafts, notes, and their photos will be permanently removed."
        confirm="Reset all data"
        onCancel={() => setResetting(false)}
        onConfirm={() =>
          void reset().then((ok) => {
            if (ok) {
              setResetting(false);
              router.dismissAll();
              router.replace("/");
            }
          })
        }
      />
      <ConfirmDialog
        visible={replacing}
        title="Replace the unfinished draft?"
        message="The draft and its photo will be removed before starting the selected scenario. Saved assessments will remain."
        confirm="Replace draft"
        onCancel={() => setReplacing(false)}
        onConfirm={() =>
          void discardDraft().then(async (ok) => {
            if (ok && (await startDraft())) {
              setReplacing(false);
              router.push("/capture");
            }
          })
        }
      />
    </Screen>
  );
}
