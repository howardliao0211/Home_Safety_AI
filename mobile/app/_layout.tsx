import { AuthProvider, useAuth } from "@/auth/context";
import { AuthScreen } from "@/auth/screen";
import { apiEnabled } from "@/api/config";
import { useEffect, useState } from "react";
import { AccessibilityInfo, ActivityIndicator, View } from "react-native";
import { Stack, router } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { ThemeProvider, DefaultTheme } from "expo-router/react-navigation";
import { PreviewProvider, usePreview } from "@/hooks/preview-context";
import { Button, Copy } from "@/components/ui";
import { colors } from "@/components/theme";

function Navigation() {
  const { ready, busy, error, initialize } = usePreview();
  const [reduceMotion, setReduceMotion] = useState(true);
  useEffect(() => {
    void AccessibilityInfo.isReduceMotionEnabled().then(setReduceMotion);
    const subscription = AccessibilityInfo.addEventListener(
      "reduceMotionChanged",
      setReduceMotion,
    );
    return () => subscription.remove();
  }, []);
  if (!ready)
    return (
      <View
        style={{
          flex: 1,
          justifyContent: "center",
          padding: 28,
          gap: 20,
          backgroundColor: colors.background,
        }}
      >
        <Copy kind="heading">
          {error
            ? apiEnabled
              ? "Could not open your checklist"
              : "Local data is unavailable"
            : "Opening your home checklist…"}
        </Copy>
        {error ? (
          <>
            <Copy>{error}</Copy>
            <Copy kind="small">
              {apiEnabled
                ? "Your saved input has not been cleared. Check your connection and retry."
                : "Your existing data has not been cleared. Check available storage and try again."}
            </Copy>
            <Button
              label={
                apiEnabled ? "Retry connecting" : "Retry opening local data"
              }
              onPress={() => void initialize()}
              disabled={busy}
            />
          </>
        ) : (
          <ActivityIndicator color={colors.accent} />
        )}
      </View>
    );
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: colors.background },
        headerShadowVisible: false,
        headerTintColor: colors.ink,
        headerTitleStyle: { fontSize: 17, fontWeight: "600" },
        contentStyle: { backgroundColor: colors.background },
        animation: reduceMotion ? "none" : "default",
        headerRight: () =>
          __DEV__ && !apiEnabled ? (
            <Button
              label="Preview tools"
              shortLabel="Preview"
              variant="text"
              onPress={() => router.push("/preview")}
              disabled={busy}
            />
          ) : apiEnabled ? (
            <Button
              label="Account"
              variant="text"
              onPress={() => router.push("/account")}
            />
          ) : null,
      }}
    >
      <Stack.Screen
        name="index"
        options={{ title: "Home Safety", headerBackVisible: false }}
      />
      <Stack.Screen name="account" options={{ title: "Account" }} />
      <Stack.Screen name="capture" options={{ title: "Your room" }} />
      <Stack.Screen name="confirm" options={{ title: "Ready to review" }} />
      <Stack.Screen
        name="analysis/[id]"
        options={{
          title: "Room assessment",
          headerBackVisible: false,
          headerLeft: () => null,
          gestureEnabled: false,
        }}
      />
      <Stack.Screen
        name="assessment/[id]"
        options={{
          title: "Your checklist",
          headerBackVisible: false,
          headerLeft: () => null,
        }}
      />
      <Stack.Screen
        name="finding/[assessmentId]/[findingId]"
        options={{ title: "Finding details" }}
      />
      <Stack.Screen
        name="evidence/[assessmentId]/[findingId]"
        options={{ title: "Add evidence" }}
      />
      <Stack.Screen name="preview" options={{ title: "Preview tools" }} />
    </Stack>
  );
}
function AssessmentLayout() {
  const auth = useAuth();
  return (
    <PreviewProvider
      key={apiEnabled ? auth.scope : "preview"}
      session={{
        ...auth,
        scope: apiEnabled ? auth.scope : "home-safety-preview-v1",
      }}
    >
      <ThemeProvider
        value={{
          ...DefaultTheme,
          colors: {
            ...DefaultTheme.colors,
            primary: colors.accent,
            background: colors.background,
            card: colors.background,
            text: colors.ink,
            border: colors.line,
          },
        }}
      >
        <View
          style={{
            flex: 1,
            backgroundColor:
              process.env.EXPO_OS === "web" ? "#e6e9e2" : colors.background,
          }}
        >
          <View
            style={{
              flex: 1,
              width: "100%",
              maxWidth: process.env.EXPO_OS === "web" ? 760 : undefined,
              alignSelf: "center",
              backgroundColor: colors.background,
            }}
          >
            <StatusBar style="dark" />
            <Navigation />
          </View>
        </View>
      </ThemeProvider>
    </PreviewProvider>
  );
}

function AuthGate() {
  const auth = useAuth();
  if (apiEnabled && !auth.ready)
    return (
      <View
        style={{
          flex: 1,
          justifyContent: "center",
          padding: 24,
          backgroundColor: colors.background,
        }}
      >
        <ActivityIndicator color={colors.accent} />
        <Copy>{auth.message || "Opening your account…"}</Copy>
      </View>
    );
  if (
    apiEnabled &&
    (auth.blocked ||
      auth.receipt ||
      auth.accountRestricted ||
      !auth.user?.emailVerified)
  )
    return <AuthScreen account={auth.accountRestricted} />;
  return <AssessmentLayout />;
}
export default function RootLayout() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  );
}
