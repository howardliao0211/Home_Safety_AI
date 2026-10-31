import { View } from "react-native";
import type { Assessment } from "@/domain/model";
import { Copy } from "@/components/ui";
import { colors } from "@/components/theme";

/** New results show saved structured suggestions; legacy records keep their prose. */
export function AssessmentSummary({
  assessment,
}: {
  assessment: Pick<Assessment, "summary" | "suggestions">;
}) {
  const { suggestions, summary } = assessment;
  if (!suggestions) return summary ? <Copy>{summary}</Copy> : null;
  if (!suggestions.length) return null;
  return (
    <View style={{ gap: 10 }}>
      <Copy kind="heading" accessibilityRole="header">
        Where to start
      </Copy>
      <View accessibilityRole="list" style={{ gap: 8 }}>
        {suggestions.map((item, index) => (
          <View
            key={index}
            accessibilityRole={"listitem" as never}
            style={{ flexDirection: "row", gap: 10 }}
          >
            <View
              accessibilityElementsHidden
              importantForAccessibility="no-hide-descendants"
              style={{
                width: 7,
                height: 7,
                borderRadius: 4,
                marginTop: 10,
                backgroundColor: colors.accent,
              }}
            />
            <Copy style={{ flex: 1 }}>{item}</Copy>
          </View>
        ))}
      </View>
    </View>
  );
}
