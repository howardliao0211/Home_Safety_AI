import { useState } from "react";
import { router } from "expo-router";
import { usePreview } from "@/hooks/preview-context";
import { Button, Copy, Dialog, useDialogAction } from "./ui";

export function NewAssessmentButton({
  label = "Assess a room",
  secondary = false,
}: {
  label?: string;
  secondary?: boolean;
}) {
  const { state, startDraft } = usePreview();
  const [choosing, setChoosing] = useState(false);
  const action = useDialogAction(choosing);
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
      <Dialog visible={choosing} onRequestClose={() => setChoosing(false)}>
        <Copy kind="heading" accessibilityRole="header">
          You have an unfinished room
        </Copy>
        <Copy>
          Resume your saved draft, or discard it to start a new room assessment.
          Your previous assessments will stay saved.
        </Copy>
        {action.failure}
        <Button
          label="Resume draft"
          onPress={() => action.run(() => void begin())}
        />
        <Button
          label="Discard draft and start new"
          variant="danger"
          onPress={() => action.run(() => void begin(true))}
        />
        <Button
          label="Cancel"
          variant="text"
          onPress={() => setChoosing(false)}
        />
      </Dialog>
    </>
  );
}
