import { useState } from "react";
import { Modal, View } from "react-native";
import { router } from "expo-router";
import { usePreview } from "@/hooks/preview-context";
import { Button, Copy, styles } from "./ui";

export function NewAssessmentButton({
  label = "Assess a room",
  secondary = false,
}: {
  label?: string;
  secondary?: boolean;
}) {
  const { state, startDraft } = usePreview();
  const [choosing, setChoosing] = useState(false);
  const begin = async (replace = false) => {
    const ok = await startDraft(replace);
    if (ok) {
      setChoosing(false);
      router.push("/capture");
    }
  };
  return (
    <>
      <Button
        label={label}
        icon="plus"
        variant={secondary ? "secondary" : "primary"}
        onPress={() => (state.draft ? setChoosing(true) : void begin())}
      />
      <Modal
        visible={choosing}
        transparent
        animationType="none"
        onRequestClose={() => setChoosing(false)}
      >
        <View style={styles.backdrop}>
          <View accessibilityViewIsModal role="dialog" style={styles.dialog}>
            <Copy kind="heading" accessibilityRole="header">
              You have an unfinished room
            </Copy>
            <Copy>
              Resume your saved draft, or discard it to start a new room
              assessment. Your previous assessments will stay saved.
            </Copy>
            <Button label="Resume draft" onPress={() => void begin()} />
            <Button
              label="Discard draft and start new"
              variant="danger"
              onPress={() => void begin(true)}
            />
            <Button
              label="Cancel"
              variant="text"
              onPress={() => setChoosing(false)}
            />
          </View>
        </View>
      </Modal>
    </>
  );
}
