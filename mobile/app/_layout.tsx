import { AuthProvider, useAuth } from "@/auth/context";
import { AuthScreen } from "@/auth/screen";
import { apiEnabled } from "@/api/config";
import { useEffect, useState } from "react";
import { AccessibilityInfo, Pressable, Text, View } from "react-native";
import { Stack, router } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { ThemeProvider, DefaultTheme } from "expo-router/react-navigation";
import { PreviewProvider, usePreview } from "@/hooks/preview-context";
import { Button, Copy } from "@/components/ui";
import { colors } from "@/components/theme";
import { LaunchScreen } from "@/components/brand";
import * as SplashScreen from "expo-splash-screen";

// Reveal the branded React loading/error surface as soon as its first frame exists.
void SplashScreen.preventAutoHideAsync();

function HomeLink() {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Back to Home"
      onPress={() => router.dismissTo("/")}
      style={{
        minWidth: 48,
        minHeight: 48,
        justifyContent: "center",
        paddingRight: 12,
      }}
    >
      <Text style={{ color: colors.accent, fontSize: 16 }}>Home</Text>
    </Pressable>
  );
}

function Navigation() {
  const auth = useAuth();
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
  useEffect(() => {
    if (ready && apiEnabled && auth.resetNavigation.current) {
      auth.resetNavigation.current = false;
      router.dismissAll();
      router.replace("/");
    }
  }, [ready]);
  if (!ready)
    return (
      <LaunchScreen loading={!error}>
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
        ) : null}
      </LaunchScreen>
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
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Account"
              onPress={() => router.push("/account")}
              style={{ minHeight: 48, minWidth: 48, justifyContent: "center" }}
            >
              <Text style={{ color: colors.accent, fontSize: 17 }}>
                Account
              </Text>
            </Pressable>
          ) : null,
      }}
    >
      <Stack.Screen
        name="index"
        options={{ title: "Home Safety AI", headerBackVisible: false }}
      />
      <Stack.Screen name="account" options={{ title: "Account" }} />
      <Stack.Screen name="capture" options={{ title: "Your room" }} />
      <Stack.Screen name="confirm" options={{ title: "Ready to review" }} />
      <Stack.Screen
        name="analysis/[id]"
        options={{
          title: "Room assessment",
          headerBackVisible: false,
          headerLeft: () => <HomeLink />,
        }}
      />
      <Stack.Screen
        name="assessment/[id]"
        options={{
          title: "Your checklist",
          headerBackVisible: false,
          headerLeft: () => <HomeLink />,
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
      <Stack.Screen
        name="chat/[assessmentId]/[findingId]"
        options={{ title: "Chat about it" }}
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
        scope: apiEnabled ? auth.scope : "preview",
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
      <LaunchScreen loading={!auth.bootstrapError}>
        <Copy>{auth.message || "Opening your account…"}</Copy>
        {auth.bootstrapError && (
          <Pressable
            accessibilityRole="button"
            onPress={() => void auth.initialize()}
            style={{ minHeight: 48, justifyContent: "center" }}
          >
            <Text style={{ color: colors.accent, fontSize: 17 }}>
              Retry opening account
            </Text>
          </Pressable>
        )}
      </LaunchScreen>
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
    <View
      style={{ flex: 1, backgroundColor: colors.background }}
      onLayout={() => SplashScreen.hide()}
    >
      <AuthProvider>
        <AuthGate />
      </AuthProvider>
    </View>
  );
}
