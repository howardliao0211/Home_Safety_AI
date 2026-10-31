import { Image } from "expo-image";
import { ActivityIndicator, Text, View } from "react-native";
import type { ReactNode } from "react";
import { colors } from "./theme";

export function BrandMark({ size = 104 }: { size?: number }) {
  return (
    <Image
      source={require("../../assets/splash-icon.png")}
      accessible={false}
      style={{ width: size, height: size }}
      contentFit="contain"
    />
  );
}

export function LaunchScreen({
  children,
  loading = true,
}: {
  children?: ReactNode;
  loading?: boolean;
}) {
  return (
    <View
      style={{
        flex: 1,
        backgroundColor: colors.background,
        alignItems: "center",
        justifyContent: "center",
        padding: 28,
        gap: 24,
      }}
    >
      <BrandMark />
      <Text
        accessibilityRole="header"
        style={{
          color: colors.ink,
          fontSize: 28,
          fontWeight: "600",
          textAlign: "center",
          letterSpacing: -0.5,
        }}
      >
        Home Safety AI
      </Text>
      {loading && (
        <ActivityIndicator
          accessibilityLabel="Opening Home Safety AI"
          color={colors.accent}
        />
      )}
      {children}
    </View>
  );
}
