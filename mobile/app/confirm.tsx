import { apiEnabled } from "@/api/config";
import { useEffect, useState } from "react";
import { Redirect, router } from "expo-router";
import { usePreview } from "@/hooks/preview-context";
import {
  Button,
  Copy,
  Disclaimer,
  Notice,
  Panel,
  PhotoView,
  PreviewNotice,
  Screen,
  Step,
} from "@/components/ui";

export default function ConfirmScreen() {
  const { state, create } = usePreview();
  const [invalid, setInvalid] = useState(false);
  const draft = state.draft;
  useEffect(() => setInvalid(false), [draft?.photo?.id]);
  if (!draft?.photo) return <Redirect href={draft ? "/capture" : "/"} />;
  return (
    <Screen>
      <Step number={2} label="Photo check" />
      <Copy kind="title" accessibilityRole="header">
        A good place to start.
      </Copy>
      <Copy>
        Make sure the room is visible. You can replace the photo before
        continuing.
      </Copy>
      <PhotoView
        key={draft.photo.id}
        photo={draft.photo}
        onInvalid={() => setInvalid(true)}
      />
      <Panel>
        <Copy kind="eyebrow">LOOKING OUT FOR</Copy>
        <Copy>
          {draft.profiles.join(" · ") || "Your household · General assessment"}
        </Copy>
        <Button
          label="Change photo or profiles"
          variant="text"
          onPress={() => router.dismissTo("/capture")}
        />
      </Panel>
      <Notice title="You stay in control">
        <Copy>
          Suggestions are a starting point. Review each finding and decide what
          needs attention.
        </Copy>
      </Notice>
      <Button
        label={apiEnabled ? "Create assessment" : "Create sample assessment"}
        icon="arrow"
        disabled={invalid}
        onPress={() =>
          void create().then((a) => {
            if (a) router.replace(`/analysis/${a.id}`);
          })
        }
      />
      <PreviewNotice />
      <Disclaimer />
    </Screen>
  );
}
