import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { Image } from "expo-image";
import { assessmentTitle, type HistoryItem } from "@/domain/history";
import { usePreview } from "@/hooks/preview-context";
import { roomSources } from "@/domain/samples";
import { colors, tokens } from "./theme";
import { Copy } from "./ui";
import { Icon } from "./icon";

export function HistoryRow({
  item,
  onPress,
  disabled,
}: {
  item: HistoryItem;
  onPress: () => void;
  disabled: boolean;
}) {
  const { loadRemotePhoto } = usePreview();
  const [uri, setUri] = useState(item.photo.uri);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    if (item.photo.remote && !uri && !item.photo.sample) {
      void loadRemotePhoto(item.photo.remote)
        .then((value) => {
          if (active) setUri(value);
        })
        .catch(() => {
          if (active) setFailed(true);
        });
    }
    return () => {
      active = false;
    };
  }, [item.photo.id]);
  const source = item.photo.sample
    ? roomSources[item.photo.sample]
    : uri
      ? { uri }
      : undefined;
  const fullTitle = item.title?.trim() || "Room assessment";
  const date = new Date(item.createdAt).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  const progress =
    item.status === "complete"
      ? item.openCount
        ? `${item.openCount} open ${item.openCount === 1 ? "finding" : "findings"}`
        : "All findings reviewed"
      : item.status === "running"
        ? "Analysis in progress"
        : "Analysis unfinished";
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Open ${fullTitle}, ${date}, ${progress}`}
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => ({
        flexDirection: "row",
        gap: 14,
        alignItems: "center",
        paddingVertical: 18,
        borderBottomWidth: 1,
        borderColor: colors.line,
        minHeight: 96,
        opacity: disabled ? 0.5 : pressed ? 0.7 : 1,
      })}
    >
      <View
        style={{
          width: 64,
          height: 72,
          borderRadius: tokens.controlRadius,
          overflow: "hidden",
          backgroundColor: colors.warm,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {source && !failed ? (
          <Image
            source={source}
            cachePolicy="none"
            accessible={false}
            style={{ width: 64, height: 72 }}
            contentFit="cover"
            onError={() => setFailed(true)}
          />
        ) : (
          <Icon name="image" color={colors.muted} />
        )}
      </View>
      <View style={{ flex: 1, gap: 3 }}>
        <Copy style={{ fontWeight: "600" }}>{assessmentTitle(item.title)}</Copy>
        <Copy kind="small">{date}</Copy>
        <Copy
          kind="small"
          style={{
            color: item.status === "complete" ? colors.accent : colors.muted,
          }}
        >
          {progress}
        </Copy>
      </View>
      <Icon name="chevron" size={18} />
    </Pressable>
  );
}
