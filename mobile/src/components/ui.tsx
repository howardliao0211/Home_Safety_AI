import { useEffect, useState, type ReactNode } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type TextStyle,
  type ViewStyle,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Image } from "expo-image";
import { usePreview } from "@/hooks/preview-context";
import type { Photo } from "@/domain/model";
import { Icon, type IconName } from "@/components/icon";
import { colors, tokens } from "@/components/theme";
import { apiEnabled } from "@/api/config";
import { roomSources } from "@/domain/samples";
export { roomSources } from "@/domain/samples";

export function Copy({
  children,
  kind = "body",
  style,
  ...props
}: {
  children: ReactNode;
  kind?: "body" | "title" | "heading" | "small" | "eyebrow";
  style?: TextStyle;
} & Pick<
  React.ComponentProps<typeof Text>,
  "accessibilityRole" | "accessibilityLiveRegion" | "testID"
>) {
  return (
    <Text selectable {...props} style={[styles[kind], style]}>
      {children}
    </Text>
  );
}
export function Screen({ children }: { children: ReactNode }) {
  const insets = useSafeAreaInsets();
  const { error, cleanupError, clearError, cleanup } = usePreview();
  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={process.env.EXPO_OS === "ios" ? "padding" : "height"}
      keyboardVerticalOffset={96}
    >
      <ScrollView
        keyboardShouldPersistTaps="handled"
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={[
          styles.content,
          { paddingBottom: Math.max(insets.bottom, 24) + 16 },
        ]}
      >
        {error && (
          <Notice tone="error" title="This change could not be completed">
            <Copy>{error}</Copy>
            <Button
              label="Dismiss message"
              variant="text"
              onPress={clearError}
            />
          </Notice>
        )}
        {cleanupError && (
          <Notice tone="error" title="Photo cleanup needs attention">
            <Copy>{cleanupError}</Copy>
            <Button
              label="Retry cleanup"
              variant="text"
              onPress={() => void cleanup()}
            />
          </Notice>
        )}
        {children}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
export function Button({
  label,
  onPress,
  variant = "primary",
  icon,
  disabled = false,
  loading = false,
  shortLabel,
}: {
  label: string;
  onPress: () => void;
  variant?: "primary" | "secondary" | "text" | "danger" | "destructive";
  icon?: IconName;
  disabled?: boolean;
  loading?: boolean;
  shortLabel?: string;
}) {
  const { busy } = usePreview();
  const unavailable = disabled || busy;
  const foreground =
    variant === "primary" || variant === "destructive"
      ? "#fff"
      : variant === "danger"
        ? colors.danger
        : colors.accent;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      aria-disabled={unavailable}
      aria-busy={loading}
      accessibilityState={{ disabled: unavailable, busy: loading }}
      disabled={unavailable}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        variant === "primary"
          ? { backgroundColor: colors.accent }
          : variant === "destructive"
            ? { backgroundColor: colors.danger }
            : variant === "secondary"
              ? {
                  borderWidth: 1,
                  borderColor: colors.line,
                  backgroundColor: colors.surface,
                }
              : {},
        { opacity: unavailable ? 0.48 : pressed ? 0.75 : 1 },
      ]}
    >
      {loading ? (
        <ActivityIndicator color={foreground} />
      ) : (
        icon && <Icon name={icon} color={foreground} size={20} />
      )}
      <Text
        style={{
          color: foreground,
          fontSize: 16,
          fontWeight: "600",
          flexShrink: 1,
          textAlign: "center",
        }}
      >
        {shortLabel ?? label}
      </Text>
    </Pressable>
  );
}
export function Notice({
  title,
  children,
  tone = "info",
}: {
  title: string;
  children?: ReactNode;
  tone?: "info" | "error" | "success";
}) {
  return (
    <View
      accessibilityLiveRegion="polite"
      style={[
        styles.notice,
        { backgroundColor: tone === "error" ? colors.dangerSoft : colors.soft },
      ]}
    >
      <View style={styles.row}>
        <Icon
          name={tone === "success" ? "check" : "info"}
          color={tone === "error" ? colors.danger : colors.accent}
        />
        <Copy
          kind="heading"
          style={{
            flex: 1,
            color: tone === "error" ? colors.danger : colors.ink,
          }}
        >
          {title}
        </Copy>
      </View>
      {children}
    </View>
  );
}
export function PreviewNotice() {
  return (
    <View style={styles.preview}>
      <View style={styles.row}>
        <View style={styles.previewDot} />
        <Copy kind="eyebrow">
          {apiEnabled ? "AI ASSESSMENT" : "INTERACTIVE PREVIEW"}
        </Copy>
      </View>
      <Copy kind="small">
        {apiEnabled
          ? "Photos are sent for AI analysis when you submit. Review the suggestions and decide what needs attention."
          : "Results are predefined examples. Your selected photo is not being analysed."}
      </Copy>
    </View>
  );
}
export function Disclaimer() {
  return (
    <View style={styles.disclaimer}>
      <Icon name="shield" size={20} color={colors.muted} />
      <Copy kind="small" style={{ flex: 1 }}>
        AI-generated suggestions based on visible information only; not a
        professional home safety inspection.
      </Copy>
    </View>
  );
}
export function Step({ number, label }: { number: number; label: string }) {
  return (
    <View style={styles.row}>
      <Copy kind="eyebrow">{`0${number} / 03`}</Copy>
      <View style={{ height: 1, width: 28, backgroundColor: colors.line }} />
      <Copy kind="eyebrow">{label.toUpperCase()}</Copy>
    </View>
  );
}
export function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <View style={{ gap: 12 }}>
      <Copy kind="heading" accessibilityRole="header">
        {title}
      </Copy>
      {children}
    </View>
  );
}
export function Panel({
  children,
  style,
}: {
  children: ReactNode;
  style?: ViewStyle;
}) {
  return <View style={[styles.panel, style]}>{children}</View>;
}
export function PhotoView({
  photo,
  compact = false,
  onInvalid,
}: {
  photo: Photo;
  compact?: boolean;
  onInvalid?: () => void;
}) {
  const [failed, setFailed] = useState(false);
  const [remoteUri, setRemoteUri] = useState<string>();
  const [preferRemote, setPreferRemote] = useState(false);
  const { loadRemotePhoto } = usePreview();
  const needsRemote =
    !!photo.remote && (preferRemote || (!photo.uri && !photo.sample));
  useEffect(() => {
    let cancelled = false;
    if (needsRemote && photo.remote) {
      void loadRemotePhoto(photo.remote)
        .then((uri) => {
          if (!cancelled) setRemoteUri(uri);
        })
        .catch(() => {
          if (!cancelled) setFailed(true);
        });
    }
    return () => {
      cancelled = true;
    };
  }, [needsRemote, photo.remote?.assessmentId, photo.remote?.photoId]);
  if (needsRemote && !remoteUri && !failed)
    return (
      <ActivityIndicator
        accessibilityLabel="Loading saved photo"
        color={colors.accent}
      />
    );
  const source = needsRemote
    ? remoteUri
      ? { uri: remoteUri }
      : undefined
    : photo.sample
      ? roomSources[photo.sample]
      : photo.uri
        ? { uri: photo.uri }
        : undefined;
  if (failed || !source)
    return (
      <Notice title="Photo unavailable" tone="error">
        <Copy>
          Select this photo again using the photo input controls. Existing
          findings remain saved.
        </Copy>
      </Notice>
    );
  return (
    <View style={{ gap: 8 }}>
      <Image
        cachePolicy="none"
        key={photo.id}
        source={source}
        accessibilityLabel={photo.label}
        style={{
          width: "100%",
          aspectRatio: compact ? 2.7 : 1.5,
          borderRadius: tokens.radius,
          backgroundColor: colors.warm,
        }}
        contentFit="cover"
        onError={() => {
          if (photo.remote && !needsRemote) {
            setPreferRemote(true);
            return;
          }
          setFailed(true);
          onInvalid?.();
        }}
      />
      <Copy kind="small">
        {photo.sample ? "Sample room · illustrative photo" : photo.label}
      </Copy>
    </View>
  );
}
export function ConfirmDialog({
  visible,
  title,
  message,
  confirm = "Confirm",
  cancel = "Keep it",
  onConfirm,
  onCancel,
}: {
  visible: boolean;
  title: string;
  message: string;
  confirm?: string;
  cancel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal
      visible={visible}
      transparent
      animationType="none"
      onRequestClose={onCancel}
    >
      <View style={styles.backdrop}>
        <View accessibilityViewIsModal role="dialog" style={styles.dialog}>
          <Copy kind="heading" accessibilityRole="header">
            {title}
          </Copy>
          <Copy>{message}</Copy>
          <Button label={confirm} variant="destructive" onPress={onConfirm} />
          <Button label={cancel} variant="secondary" onPress={onCancel} />
        </View>
      </View>
    </Modal>
  );
}
export const styles = StyleSheet.create({
  content: {
    paddingHorizontal: 24,
    paddingTop: 24,
    gap: 24,
    width: "100%",
    maxWidth: tokens.maxWidth,
    alignSelf: "center",
    flexGrow: 1,
  },
  body: { color: colors.ink, fontSize: 16, lineHeight: 25 },
  title: {
    color: colors.ink,
    fontSize: 32,
    lineHeight: 39,
    fontWeight: "700",
    letterSpacing: -0.8,
  },
  heading: {
    color: colors.ink,
    fontSize: 19,
    lineHeight: 26,
    fontWeight: "600",
    letterSpacing: -0.25,
  },
  small: { color: colors.muted, fontSize: 13, lineHeight: 20 },
  eyebrow: {
    color: colors.accent,
    fontSize: 11,
    lineHeight: 18,
    fontWeight: "700",
    letterSpacing: 1.5,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  button: {
    minHeight: 54,
    borderRadius: tokens.controlRadius,
    paddingVertical: 14,
    paddingHorizontal: 18,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 10,
  },
  panel: {
    padding: 20,
    borderRadius: tokens.radius,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    gap: 16,
  },
  notice: { padding: 18, borderRadius: 14, gap: 10 },
  preview: {
    gap: 5,
    paddingTop: 16,
    borderTopWidth: 1,
    borderColor: colors.line,
  },
  previewDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.accent,
  },
  disclaimer: { flexDirection: "row", gap: 10, paddingTop: 4 },
  backdrop: {
    flex: 1,
    padding: 24,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#152c2666",
  },
  dialog: {
    padding: 24,
    backgroundColor: colors.background,
    width: "100%",
    maxWidth: 420,
    borderRadius: 20,
    gap: 20,
  },
  input: {
    borderWidth: 1,
    borderColor: "#8b998e",
    borderRadius: 12,
    padding: 16,
    minHeight: 108,
    fontSize: 16,
    lineHeight: 25,
    color: colors.ink,
    backgroundColor: "#fff",
    textAlignVertical: "top",
  },
});
