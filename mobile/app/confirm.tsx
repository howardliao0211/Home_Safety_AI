import { apiEnabled } from "@/api/config";
import { useEffect, useState } from "react";
import { Redirect, router } from "expo-router";
import { usePreview } from "@/hooks/preview-context";
import {
  householdDetailsError,
  normalizeHouseholdDetails,
} from "@/domain/model";
import {
  Button,
  Copy,
  Notice,
  Panel,
  PhotoView,
  Screen,
  Step,
} from "@/components/ui";
import { colors } from "@/components/theme";

export default function ConfirmScreen() {
  const { state, create } = usePreview();
  const [invalid, setInvalid] = useState(false);
  const draft = state.draft;
  useEffect(() => setInvalid(false), [draft?.photo?.id]);
  if (!draft?.photo) return <Redirect href={draft ? "/capture" : "/"} />;
  const details = normalizeHouseholdDetails(draft.householdContext);
  const detailsError = householdDetailsError(draft.householdContext);
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
          {draft.profiles.join(" · ") ||
            (details
              ? "No groups selected"
              : "Your household · General assessment")}
        </Copy>
        <Copy kind="eyebrow" style={{ textTransform: "uppercase" }}>
          Household details
        </Copy>
        <Copy style={details ? undefined : { color: colors.muted }}>
          {details || "No additional details"}
        </Copy>
        {!!detailsError && (
          <Copy
            accessibilityRole="alert"
            accessibilityLiveRegion="polite"
            style={{ color: colors.danger, fontWeight: "600" }}
          >
            {detailsError}
          </Copy>
        )}
        <Button
          label="Edit photo or household details"
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
        disabled={invalid || !!detailsError}
        onPress={() =>
          void create().then((a) => {
            if (a) router.replace(`/analysis/${a.id}`);
          })
        }
      />
    </Screen>
  );
}
