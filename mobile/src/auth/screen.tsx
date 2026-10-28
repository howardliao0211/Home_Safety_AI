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

export function AuthScreen({ account = false }: { account?: boolean }) {
  const auth = useAuth();
  const [mode, setMode] = useState<"login" | "signup" | "reset">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const [message, setMessage] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const passwordRef = useRef<React.ComponentRef<typeof TextInput>>(null);
  const insets = useSafeAreaInsets();
  const verified = auth.user?.emailVerified;
  async function act(work: () => Promise<unknown>, success = "") {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setMessage("");
    try {
      await work();
      setMessage(success);
    } catch (error) {
      setMessage(authMessage(error));
    } finally {
      setPassword("");
      working.current = false;
      setBusy(false);
    }
  }
  useEffect(() => {
    if (message) AccessibilityInfo.announceForAccessibility(message);
  }, [message]);
  useEffect(() => {
    if (!auth.receipt) return;
    const timer = setInterval(() => {
      if (!working.current) void act(auth.pollDeletion);
    }, 5000);
    return () => clearInterval(timer);
  }, [auth.receipt]);
  const Action = ({
    label,
    onPress,
    danger = false,
    primary = false,
  }: {
    label: string;
    onPress: () => void;
    danger?: boolean;
    primary?: boolean;
  }) => (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: busy, busy }}
      disabled={busy}
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
        opacity: busy ? 0.5 : pressed ? 0.8 : 1,
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
            <Action
              primary
              label="Check deletion status"
              onPress={() =>
                void act(
                  auth.pollDeletion,
                  "Cleanup is still pending if completion has not appeared.",
                )
              }
            />
            <Action
              label="Sign out while cleanup continues"
              onPress={() => void act(auth.logout)}
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
                <Action
                  primary
                  label="I’ve verified my email"
                  onPress={() => void act(auth.refresh)}
                />
                <Action
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
            <Action label="Sign out" onPress={() => void act(auth.logout)} />
            {!confirmDelete ? (
              <Action
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
                  value={password}
                  onChangeText={setPassword}
                  secureTextEntry={!visible}
                  autoComplete="current-password"
                  textContentType="password"
                  autoCapitalize="none"
                  style={{
                    ...text,
                    borderWidth: 1,
                    borderColor: colors.ink,
                    borderRadius: 10,
                    padding: 14,
                    minHeight: 48,
                  }}
                />
                <Action
                  label={visible ? "Hide password" : "Show password"}
                  onPress={() => setVisible(!visible)}
                />
                <Action
                  label="Permanently delete account"
                  danger
                  onPress={() => {
                    if (!password)
                      setMessage("Enter your password to confirm.");
                    else void act(() => auth.deleteAccount(password));
                  }}
                />
                <Action
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
                  borderColor: colors.ink,
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
                    borderColor: colors.ink,
                    borderRadius: 10,
                    padding: 14,
                    minHeight: 48,
                  }}
                />
                <Action
                  label={visible ? "Hide password" : "Show password"}
                  onPress={() => setVisible(!visible)}
                />
                {mode === "signup" && (
                  <Text style={text}>
                    Use a strong password with at least 12 characters, including
                    uppercase, lowercase, a number and a symbol.
                  </Text>
                )}
              </View>
            )}
            <Action
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
                <Action
                  label="Forgot password?"
                  onPress={() => {
                    setMode("reset");
                    setPassword("");
                    setMessage("");
                  }}
                />
                <Action
                  label="Create account"
                  onPress={() => {
                    setMode("signup");
                    setPassword("");
                    setMessage("");
                  }}
                />
              </>
            ) : (
              <Action
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
