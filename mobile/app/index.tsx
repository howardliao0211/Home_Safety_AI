import { View } from "react-native";
import { Redirect, router, type Href } from "expo-router";
import { destination, latest } from "@/domain/model";
import { usePreview } from "@/hooks/preview-context";
import { Icon } from "@/components/icon";
import {
  Button,
  Copy,
  Disclaimer,
  Panel,
  PhotoView,
  PreviewNotice,
  Screen,
  styles,
} from "@/components/ui";
import { colors } from "@/components/theme";

export default function StartScreen() {
  const { state, startDraft } = usePreview();
  const assessment = latest(state);
  if (state.draft) return <Redirect href="/capture" />;
  if (assessment) return <Redirect href={destination(assessment) as Href} />;
  return (
    <Screen>
      <View style={styles.row}>
        <View
          style={{
            padding: 12,
            backgroundColor: colors.soft,
            borderRadius: 16,
          }}
        >
          <Icon name="home" size={27} />
        </View>
        <Copy kind="eyebrow">A LITTLE CARE. EVERY DAY.</Copy>
      </View>
      <View style={{ gap: 12 }}>
        <Copy kind="title" accessibilityRole="header">
          A fresh look at{"\n"}the place you call home.
        </Copy>
        <Copy style={{ color: colors.muted }}>
          Turn a room photo into a practical checklist for the people you care
          about.
        </Copy>
      </View>
      <PreviewNotice />
      <Button
        label="Start with a room"
        icon="arrow"
        onPress={() =>
          void startDraft().then((ok) => {
            if (ok) router.push("/capture");
          })
        }
      />
      <PhotoView
        photo={{
          id: "welcome",
          label: "A comfortable living room",
          sample: "living",
        }}
      />
      <Panel>
        <Copy kind="heading">One room. A few thoughtful steps.</Copy>
        {[
          [
            "01",
            "Choose a room photo",
            "Take a photo, choose one, or explore a sample.",
          ],
          [
            "02",
            "See what needs attention",
            "Read potential concerns and ask for a closer look.",
          ],
          [
            "03",
            "Make a plan, at your pace",
            "Work through your checklist. You make the final call.",
          ],
        ].map(([number, title, text]) => (
          <View key={number} style={{ flexDirection: "row", gap: 16 }}>
            <Copy kind="eyebrow" style={{ paddingTop: 3 }}>
              {number}
            </Copy>
            <View style={{ flex: 1, gap: 3 }}>
              <Copy style={{ fontWeight: "600" }}>{title}</Copy>
              <Copy kind="small">{text}</Copy>
            </View>
          </View>
        ))}
      </Panel>
      <Disclaimer />
    </Screen>
  );
}
