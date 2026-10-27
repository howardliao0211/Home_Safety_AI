import { Pressable, View } from "react-native";
import { router } from "expo-router";
import type { Finding } from "@/domain/model";
import { usePreview } from "@/hooks/preview-context";
import { Icon } from "@/components/icon";
import { Copy, Panel, styles } from "@/components/ui";
import { colors } from "@/components/theme";

export function Severity({ severity }: { severity: Finding["severity"] }) {
  return (
    <View
      style={{
        paddingHorizontal: 10,
        paddingVertical: 4,
        borderRadius: 6,
        backgroundColor:
          severity === "High"
            ? colors.dangerSoft
            : severity === "Medium"
              ? colors.amberSoft
              : colors.soft,
        alignSelf: "flex-start",
      }}
    >
      <Copy
        kind="small"
        style={{
          fontWeight: "600",
          color:
            severity === "High"
              ? colors.danger
              : severity === "Medium"
                ? colors.amber
                : colors.accent,
        }}
      >
        {severity} priority
      </Copy>
    </View>
  );
}
export function FindingCard({
  finding,
  assessmentId,
  index,
}: {
  finding: Finding;
  assessmentId: string;
  index: number;
}) {
  const { busy, changeStatus } = usePreview();
  return (
    <Panel style={{ gap: 14 }}>
      <View
        style={{
          ...styles.row,
          justifyContent: "space-between",
          flexWrap: "wrap",
        }}
      >
        <Severity severity={finding.severity} />
        <Copy kind="eyebrow">{`0${index + 1} · ${finding.category.toUpperCase()}`}</Copy>
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`View ${finding.title}`}
        onPress={() => router.push(`/finding/${assessmentId}/${finding.id}`)}
        style={({ pressed }) => ({
          opacity: pressed ? 0.7 : 1,
          minHeight: 60,
          gap: 8,
        })}
      >
        <View style={styles.row}>
          <Copy kind="heading" style={{ flex: 1 }}>
            {finding.title}
          </Copy>
          <Icon name="chevron" size={18} />
        </View>
        <Copy style={{ color: colors.muted, fontSize: 15 }}>
          {finding.shortAction}
        </Copy>
      </Pressable>
      <View
        style={{ borderTopWidth: 1, borderColor: colors.line, paddingTop: 8 }}
      >
        <Pressable
          accessibilityRole="checkbox"
          accessibilityLabel={`${finding.status === "open" ? "Mark resolved" : "Reopen"}: ${finding.title}`}
          aria-checked={finding.status === "resolved"}
          aria-disabled={busy}
          accessibilityState={{
            checked: finding.status === "resolved",
            disabled: busy,
          }}
          disabled={busy}
          onPress={() =>
            void changeStatus(
              assessmentId,
              finding.id,
              finding.status === "open" ? "resolved" : "open",
            )
          }
          style={({ pressed }) => ({
            ...styles.row,
            minHeight: 48,
            opacity: busy ? 0.5 : pressed ? 0.7 : 1,
          })}
        >
          <View
            style={{
              width: 25,
              height: 25,
              borderWidth: 1.5,
              borderColor:
                finding.status === "resolved" ? colors.accent : "#809286",
              backgroundColor:
                finding.status === "resolved" ? colors.accent : "transparent",
              borderRadius: 7,
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {finding.status === "resolved" && (
              <Icon name="check" size={18} color="#fff" />
            )}
          </View>
          <Copy style={{ fontSize: 14, fontWeight: "600", flex: 1 }}>
            {finding.status === "open"
              ? "Mark resolved"
              : finding.status === "resolved"
                ? "Resolved · Tap to reopen"
                : "Dismissed · Tap to reopen"}
          </Copy>
        </Pressable>
      </View>
    </Panel>
  );
}
