import { useEffect, useRef, useState } from "react";
import {
  AccessibilityInfo,
  ActivityIndicator,
  KeyboardAvoidingView,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors } from "@/components/theme";
import { authMessage, useAuth } from "./context";

function AuthAction({
  busy = false,
  label,
  onPress,
  danger = false,
  primary = false,
  disabled = false,
}: {
  busy?: boolean;
  label: string;
  onPress: () => void;
  danger?: boolean;
  primary?: boolean;
  disabled?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: busy || disabled, busy }}
      disabled={busy || disabled}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: 48,
        borderRadius: 12,
        justifyContent: "center",
        padding: 14,
        backgroundColor: danger
          ? colors.danger
          : primary
            ? colors.accent
            : "transparent",
        opacity: busy || disabled ? 0.5 : pressed ? 0.8 : 1,
      })}
    >
      <Text
        style={{
          color: danger || primary ? "white" : colors.accent,
          fontSize: 17,
          fontWeight: "600",
          textAlign: "center",
        }}
      >
        {label}
      </Text>
    </Pressable>
  );
}

export function AuthScreen({
  account = false,
  onRefresh,
  refreshDisabled = false,
}: {
  account?: boolean;
  onRefresh?: () => Promise<void>;
  refreshDisabled?: boolean;
}) {
  const auth = useAuth();
  const [mode, setMode] = useState<"login" | "signup" | "reset">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [focused, setFocused] = useState<string | null>(null);
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const leaving = useRef(false);
  const [message, setMessage] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const passwordRef = useRef<React.ComponentRef<typeof TextInput>>(null);
  const insets = useSafeAreaInsets();
  const verified = auth.user?.emailVerified;
  useEffect(() => {
    if (auth.deletionComplete) setMode("login");
  }, [auth.deletionComplete]);
  async function act(work: () => Promise<unknown>, success = "") {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setMessage("");
    try {
      await work();
      setMessage(success);
    } catch (error) {
      if ((error as { code?: string }).code !== "session_changed")
        setMessage(authMessage(error));
    } finally {
      setPassword("");
      working.current = false;
      setBusy(false);
    }
  }
  useEffect(() => {
    const notice = message || auth.message;
    if (notice) AccessibilityInfo.announceForAccessibility(notice);
  }, [message, auth.message]);
  useEffect(() => {
    if (!auth.receipt) return;
    const timer = setInterval(() => {
      if (!working.current) void act(auth.pollDeletion);
    }, 5000);
    return () => clearInterval(timer);
  }, [auth.receipt]);
  const text = { fontSize: 17, lineHeight: 25, color: colors.ink };
  const heading = auth.receipt
    ? "Deleting your account"
    : account
      ? "Your account"
      : auth.user
        ? "Verify your email"
        : mode === "signup"
          ? "Create account"
          : mode === "reset"
            ? "Reset password"
            : "Sign in";
  function submit() {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setMessage("Enter a valid email address.");
      return;
    }
    if (mode !== "reset" && !password) {
      setMessage("Enter your password.");
      return;
    }
    if (mode === "reset")
      void act(
        () => auth.reset(email),
        "If an account can receive a reset email, you’ll receive a link. Open it in your browser, then return here to sign in.",
      );
    else
      void act(() =>
        mode === "signup"
          ? auth.register(email, password)
          : auth.login(email, password),
      );
  }
  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: colors.background }}
      behavior={process.env.EXPO_OS === "ios" ? "padding" : "height"}
    >
      <ScrollView
        keyboardShouldPersistTaps="handled"
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={{
          paddingTop: insets.top + 24,
          paddingBottom: insets.bottom + 24,
          paddingHorizontal: 24,
          gap: 20,
          maxWidth: 520,
          width: "100%",
          alignSelf: "center",
        }}
      >
        <Text style={{ ...text, color: colors.accent, fontWeight: "600" }}>
          Home Safety
        </Text>
        <Text
          accessibilityRole="header"
          style={{ ...text, fontSize: 28, lineHeight: 36, fontWeight: "700" }}
        >
          {heading}
        </Text>
        {!!(message || auth.message) && (
          <Text selectable accessibilityLiveRegion="polite" style={text}>
            {message || auth.message}
          </Text>
        )}
        {busy && (
          <ActivityIndicator
            accessibilityLabel="Working"
            color={colors.accent}
          />
        )}
        {auth.receipt ? (
          <>
            <Text style={text}>
              Your assessments, photos and highlights are being removed. Cleanup
              continues if you close the app. This can take several minutes;
              deletion is complete only when confirmed here.
            </Text>
            <AuthAction
              busy={busy}
              primary
              label="Check deletion status"
              onPress={() =>
                void act(
                  auth.pollDeletion,
                  "Cleanup is still pending if completion has not appeared.",
                )
              }
            />
            <AuthAction
              label="Sign out while cleanup continues"
              disabled={leaving.current}
              onPress={() => {
                if (leaving.current) return;
                leaving.current = true;
                void auth
                  .logout()
                  .catch((error) => setMessage(authMessage(error)))
                  .finally(() => {
                    leaving.current = false;
                  });
              }}
            />
          </>
        ) : auth.user ? (
          <>
            <Text selectable style={text}>
              {auth.user.email}
            </Text>
            {!verified && (
              <>
                <Text style={text}>
                  Open the verification email in your browser, then return to
                  this app and refresh. If the link expired or is invalid,
                  request a new one.
                </Text>
                <AuthAction
                  busy={busy}
                  primary
                  label="I’ve verified my email"
                  onPress={() => void act(auth.refresh)}
                />
                <AuthAction
                  busy={busy}
                  label="Resend verification email"
                  onPress={() =>
                    void act(
                      auth.resend,
                      "Verification email sent. Check your inbox.",
                    )
                  }
                />
              </>
            )}
            {account && verified && onRefresh && (
              <AuthAction
                busy={busy}
                primary
                label="Refresh latest assessment"
                disabled={refreshDisabled}
                onPress={() => void act(onRefresh)}
              />
            )}
            <AuthAction
              busy={busy}
              label="Sign out"
              onPress={() => void act(auth.logout)}
            />
            {!confirmDelete ? (
              <AuthAction
                busy={busy}
                label="Delete account"
                danger
                onPress={() => {
                  setConfirmDelete(true);
                  setPassword("");
                }}
              />
            ) : (
              <>
                <Text style={text}>
                  Permanently delete your account, all assessments, photos and
                  highlights. There is no recovery grace period. Enter your
                  password again to confirm.
                </Text>
                <Text style={text}>Password</Text>
                <TextInput
                  accessibilityLabel="Password"
                  onFocus={() => setFocused("password")}
                  onBlur={() => setFocused(null)}
                  value={password}
                  onChangeText={setPassword}
                  secureTextEntry={!visible}
                  autoComplete="current-password"
                  textContentType="password"
                  autoCapitalize="none"
                  style={{
                    ...text,
                    borderWidth: 1,
                    borderColor:
                      focused === "password" ? colors.accent : colors.ink,
                    borderRadius: 10,
                    padding: 14,
                    minHeight: 48,
                  }}
                />
                <AuthAction
                  busy={busy}
                  label={visible ? "Hide password" : "Show password"}
                  onPress={() => setVisible(!visible)}
                />
                <AuthAction
                  busy={busy}
                  label="Permanently delete account"
                  danger
                  onPress={() => {
                    if (!password)
                      setMessage("Enter your password to confirm.");
                    else void act(() => auth.deleteAccount(password));
                  }}
                />
                <AuthAction
                  busy={busy}
                  label="Cancel deletion"
                  onPress={() => {
                    setConfirmDelete(false);
                    setPassword("");
                  }}
                />
              </>
            )}
          </>
        ) : (
          <>
            {auth.deletionComplete && (
              <Text style={text}>
                Your account and associated data have been deleted.
              </Text>
            )}
            <View style={{ gap: 8 }}>
              <Text style={text}>Email</Text>
              <TextInput
                accessibilityLabel="Email"
                onFocus={() => setFocused("email")}
                onBlur={() => setFocused(null)}
                value={email}
                onChangeText={setEmail}
                keyboardType="email-address"
                autoCapitalize="none"
                autoCorrect={false}
                autoComplete="email"
                textContentType="emailAddress"
                returnKeyType={mode === "reset" ? "send" : "next"}
                submitBehavior="submit"
                onSubmitEditing={() =>
                  mode === "reset" ? submit() : passwordRef.current?.focus()
                }
                style={{
                  ...text,
                  borderWidth: 1,
                  borderColor: focused === "email" ? colors.accent : colors.ink,
                  borderRadius: 10,
                  padding: 14,
                  minHeight: 48,
                }}
              />
            </View>
            {mode !== "reset" && (
              <View style={{ gap: 8 }}>
                <Text style={text}>Password</Text>
                <TextInput
                  ref={passwordRef}
                  accessibilityLabel="Password"
                  onFocus={() => setFocused("password")}
                  onBlur={() => setFocused(null)}
                  value={password}
                  onChangeText={setPassword}
                  secureTextEntry={!visible}
                  autoCapitalize="none"
                  autoCorrect={false}
                  autoComplete={
                    mode === "signup" ? "new-password" : "current-password"
                  }
                  textContentType={
                    mode === "signup" ? "newPassword" : "password"
                  }
                  returnKeyType="go"
                  onSubmitEditing={submit}
                  style={{
                    ...text,
                    borderWidth: 1,
                    borderColor:
                      focused === "password" ? colors.accent : colors.ink,
                    borderRadius: 10,
                    padding: 14,
                    minHeight: 48,
                  }}
                />
                <AuthAction
                  busy={busy}
                  label={visible ? "Hide password" : "Show password"}
                  onPress={() => setVisible(!visible)}
                />
                {mode === "signup" && (
                  <Text style={text}>
                    Use at least 9 characters, including a lowercase letter and
                    a number.
                  </Text>
                )}
              </View>
            )}
            <AuthAction
              busy={busy}
              primary
              label={
                mode === "signup"
                  ? "Create account"
                  : mode === "reset"
                    ? "Send reset email"
                    : "Sign in"
              }
              onPress={submit}
            />
            {mode === "login" ? (
              <>
                <AuthAction
                  busy={busy}
                  label="Forgot password?"
                  onPress={() => {
                    setMode("reset");
                    setPassword("");
                    setMessage("");
                  }}
                />
                <AuthAction
                  busy={busy}
                  label="Create account"
                  onPress={() => {
                    setMode("signup");
                    setPassword("");
                    setMessage("");
                  }}
                />
              </>
            ) : (
              <AuthAction
                busy={busy}
                label="Back to sign in"
                onPress={() => {
                  setMode("login");
                  setPassword("");
                  setMessage("");
                }}
              />
            )}
          </>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
