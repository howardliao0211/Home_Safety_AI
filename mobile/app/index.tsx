import { useCallback, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { router, useFocusEffect, type Href } from "expo-router";
import { destination } from "@/domain/model";
import { usePreview } from "@/hooks/preview-context";
import { NewAssessmentButton } from "@/components/new-assessment-button";
import { HistoryRow } from "@/components/history-row";
import { BrandMark } from "@/components/brand";
import {
  Button,
  Copy,
  Disclaimer,
  Notice,
  Panel,
  PreviewNotice,
  Screen,
} from "@/components/ui";
import { colors } from "@/components/theme";

export default function HomeScreen() {
  const {
    state,
    busy,
    history,
    historyLoading,
    historyError,
    historyLoaded,
    historyCursor,
    loadHistory,
    retryHistory,
    loadAssessment,
  } = usePreview();
  const [openingError, setOpeningError] = useState(false);
  useFocusEffect(
    useCallback(() => {
      if (!historyLoaded) void loadHistory();
    }, [historyLoaded]),
  );
  const open = async (id: string) => {
    setOpeningError(false);
    const assessment = await loadAssessment(id);
    if (assessment) router.push(destination(assessment) as Href);
    else setOpeningError(true);
  };
  return (
    <Screen>
      <View style={{ flexDirection: "row", gap: 16, alignItems: "center" }}>
        <BrandMark size={52} />
        <View style={{ flex: 1, gap: 4 }}>
          <Copy kind="eyebrow">A LITTLE CARE. EVERY DAY.</Copy>
          <Copy kind="title" accessibilityRole="header">
            Your home,{"\n"}one room at a time.
          </Copy>
        </View>
      </View>
      <Copy style={{ color: colors.muted }}>
        A fresh look at your space, and a practical next step for the people you
        care about.
      </Copy>
      <NewAssessmentButton />
      {state.draft && (
        <Panel>
          <Copy kind="heading">Continue where you left off</Copy>
          <Copy kind="small">
            Your unfinished room is saved on this device.
          </Copy>
          <Button
            label="Resume assessment"
            variant="secondary"
            icon="arrow"
            onPress={() => router.push("/capture")}
          />
        </Panel>
      )}
      <View style={{ gap: 8 }}>
        <Copy kind="heading" accessibilityRole="header">
          Previous assessments
        </Copy>
        <Button
          label="Refresh history"
          variant="text"
          icon="refresh"
          disabled={historyLoading}
          onPress={() => void loadHistory()}
        />
        {historyLoading && (
          <ActivityIndicator
            color={colors.accent}
            accessibilityLabel="Loading assessment history"
          />
        )}
        {historyError && (
          <Notice title="History could not load" tone="error">
            <Copy>{historyError}</Copy>
            <Button
              label="Retry loading history"
              variant="text"
              disabled={historyLoading}
              onPress={() => void retryHistory()}
            />
          </Notice>
        )}
        {openingError && (
          <Notice title="Assessment unavailable" tone="error">
            <Copy>
              We could not open this assessment. Refresh history or select it
              again to retry.
            </Copy>
          </Notice>
        )}
        {historyLoaded &&
          !historyLoading &&
          !historyError &&
          history.length === 0 && (
            <Panel>
              <Copy kind="heading">Start with a familiar room</Copy>
              <Copy>
                Your previous assessments will appear here. Take or choose a
                room photo to begin.
              </Copy>
            </Panel>
          )}
        {history.map((item) => (
          <HistoryRow
            key={item.id}
            item={item}
            disabled={busy}
            onPress={() => void open(item.id)}
          />
        ))}
        {historyCursor && (
          <Button
            label="Load more"
            variant="secondary"
            disabled={historyLoading}
            onPress={() => void loadHistory(true)}
          />
        )}
      </View>
      <PreviewNotice />
      <Disclaimer />
    </Screen>
  );
}
