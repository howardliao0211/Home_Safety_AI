import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  signOut,
  sendEmailVerification,
  sendPasswordResetEmail,
  onIdTokenChanged,
  EmailAuthProvider,
  reauthenticateWithCredential,
  validatePassword,
  type User,
} from "firebase/auth";
import { auth, receiptStorage, checkSessionPersistence } from "./firebase";
import { firebaseConfig, emulatorUrl } from "./config";
import { accountScope, apiConfig } from "@/api/config";
import { ApiError } from "@/api/backend-client";

export function authMessage(error: unknown) {
  const code = (error as { code?: string })?.code;
  if (code === "auth/network-request-failed")
    return "Could not connect. Check your connection and retry.";
  if (code === "auth/too-many-requests")
    return "Please wait a moment before trying again.";
  if (
    code === "auth/weak-password" ||
    code === "auth/password-does-not-meet-requirements"
  )
    return "Choose a stronger password that meets the requirements.";
  if (error instanceof ApiError) return error.message;
  return "The request could not be completed. Check your details and try again.";
}

function useAccountState() {
  const [user, setUser] = useState<User | null>(null);
  const [bootstrapError, setBootstrapError] = useState(false);
  const [ready, setReady] = useState(false);
  const [message, setMessage] = useState("");
  const [receipt, setReceipt] = useState<string | null>(null);
  const [deletionComplete, setDeletionComplete] = useState(false);
  const [accountRestricted, setAccountRestricted] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const generation = useRef(0);
  const accountRequests = useRef(new Set<AbortController>());
  function invalidateRequests() {
    generation.current++;
    accountRequests.current.forEach((controller) => controller.abort());
    accountRequests.current.clear();
  }
  const resetNavigation = useRef(false);
  const lastUid = useRef<string | null>(null);
  const cleanups = useRef(new Set<() => Promise<void>>());
  const receiptKey = `deletion:${firebaseConfig.projectId}:${apiConfig.baseUrl}`;
  const clearLocal = async () => {
    await Promise.all([...cleanups.current].map((cleanup) => cleanup()));
  };
  useEffect(() => {
    let active = true;
    const unsubscribe = onIdTokenChanged(auth, async (next) => {
      if (!active) return;
      if (lastUid.current && lastUid.current !== next?.uid) {
        invalidateRequests();
        resetNavigation.current = true;
        setBlocked(true);
        try {
          await clearLocal();
        } catch {
          setMessage("Local cleanup failed. Retry sign-out from Account.");
        }
        if (!active) return;
        setBlocked(false);
      }
      lastUid.current = next?.uid ?? null;
      setUser(next);
    });
    void initialize();
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);
  async function initialize() {
    setBootstrapError(false);
    setMessage("");
    try {
      await auth.authStateReady();
      await checkSessionPersistence();
      const saved = await receiptStorage.getItem(receiptKey);
      setUser(auth.currentUser);
      setReceipt(saved);
      setReady(true);
    } catch (error) {
      setMessage(authMessage(error));
      setBootstrapError(true);
    }
  }
  async function logout() {
    invalidateRequests();
    resetNavigation.current = true;
    setBlocked(true);
    try {
      await clearLocal();
      lastUid.current = null;
      await signOut(auth);
      setUser(null);
      setAccountRestricted(false);
      setDeletionComplete(false);
      setReceipt(null);
    } finally {
      setBlocked(false);
    }
  }
  async function getToken() {
    const current = auth.currentUser;
    if (!current || current.uid !== user?.uid || blocked)
      throw new Error("Sign in again to continue.");
    try {
      return await current.getIdToken();
    } catch (error) {
      const code = (error as { code?: string }).code;
      if (
        [
          "auth/user-token-expired",
          "auth/user-disabled",
          "auth/invalid-user-token",
        ].includes(code || "")
      ) {
        setMessage("Your session expired. Sign in again to continue.");
        await logout();
      }
      throw error;
    }
  }
  async function onAuthError(error: ApiError) {
    if (error.code === "account_deleting") {
      setAccountRestricted(true);
      setBlocked(true);
      await clearLocal();
      setMessage(
        "This account is being deleted. Reauthenticate from Account to recover its status.",
      );
      setBlocked(false);
    } else {
      setMessage("Your session expired. Sign in again to continue.");
      await logout();
    }
  }
  async function request(path: string, headers: Record<string, string>) {
    const epoch = generation.current;
    const controller = new AbortController();
    accountRequests.current.add(controller);
    const timer = setTimeout(() => controller.abort(), 20_000);
    try {
      const response = await fetch(apiConfig.baseUrl + path, {
        method: "POST",
        headers,
        signal: controller.signal,
      });
      const body = await response.json();
      if (epoch !== generation.current)
        throw new ApiError(
          "The account session changed.",
          409,
          "session_changed",
        );
      if (!response.ok)
        throw new ApiError(
          body.error?.message || "Retry when connected.",
          response.status,
          body.error?.code || "request_failed",
        );
      return body;
    } catch (error) {
      if (epoch !== generation.current)
        throw new ApiError(
          "The account session changed.",
          409,
          "session_changed",
        );
      if (error instanceof ApiError) throw error;
      throw new ApiError(
        "Could not reach the account service. Check your connection and retry.",
        503,
        "network",
      );
    } finally {
      clearTimeout(timer);
      accountRequests.current.delete(controller);
    }
  }

  return {
    user,
    ready,
    bootstrapError,
    resetNavigation,
    initialize,
    message,
    blocked,
    accountRestricted,
    receipt,
    deletionComplete,
    getToken,
    onAuthError,
    scope: user
      ? accountScope(firebaseConfig.projectId, user.uid)
      : "home-safety-preview-v1",
    registerCleanup: (cleanup: () => Promise<void>) => {
      cleanups.current.add(cleanup);
      return () => {
        cleanups.current.delete(cleanup);
      };
    },
    logout,
    login: async (email: string, password: string) => {
      invalidateRequests();
      resetNavigation.current = true;
      setDeletionComplete(false);
      setMessage("");
      await signInWithEmailAndPassword(auth, email.trim(), password);
    },
    register: async (email: string, password: string) => {
      invalidateRequests();
      resetNavigation.current = true;
      setDeletionComplete(false);
      // Firebase's Auth emulator does not implement getPasswordPolicy. Keep the
      // documented local policy explicit; production always queries the provider.
      if (
        emulatorUrl &&
        (password.length < 12 ||
          !/[a-z]/.test(password) ||
          !/[A-Z]/.test(password) ||
          !/[0-9]/.test(password) ||
          !/[^A-Za-z0-9]/.test(password))
      ) {
        throw new ApiError(
          "Use at least 12 characters with uppercase, lowercase, a number and a symbol.",
          422,
          "password_policy",
        );
      }
      const status = emulatorUrl
        ? null
        : await validatePassword(auth, password);
      if (status && !status.isValid) {
        const missing = [
          status.meetsMinPasswordLength === false &&
            `at least ${status.passwordPolicy.customStrengthOptions.minPasswordLength} characters`,
          status.containsLowercaseLetter === false && "a lowercase letter",
          status.containsUppercaseLetter === false && "an uppercase letter",
          status.containsNumericCharacter === false && "a number",
          status.containsNonAlphanumericCharacter === false && "a symbol",
        ]
          .filter(Boolean)
          .join(", ");
        throw new ApiError(
          `Your password needs ${missing || "to meet the provider policy"}.`,
          422,
          "password_policy",
        );
      }
      const result = await createUserWithEmailAndPassword(
        auth,
        email.trim(),
        password,
      );
      // Account creation succeeds even if delivery fails: the verification gate offers resend.
      await sendEmailVerification(result.user);
    },
    resend: async () => {
      if (auth.currentUser) await sendEmailVerification(auth.currentUser);
    },
    refresh: async () => {
      if (!auth.currentUser) return;
      await auth.currentUser.reload();
      await auth.currentUser.getIdToken(true);
      setUser(auth.currentUser);
      // Force a render even when the SDK mutates the existing user object.
      setMessage(
        auth.currentUser.emailVerified
          ? "Email verified."
          : "Your email is not verified yet. Open the latest link or resend it.",
      );
    },
    reset: async (email: string) => {
      try {
        await sendPasswordResetEmail(auth, email.trim());
      } catch (error) {
        if ((error as { code?: string }).code !== "auth/user-not-found")
          throw error;
      }
    },
    deleteAccount: async (password: string) => {
      invalidateRequests();
      const epoch = generation.current;
      const current = auth.currentUser;
      if (!current?.email) throw new Error("Sign in again.");
      await reauthenticateWithCredential(
        current,
        EmailAuthProvider.credential(current.email, password),
      );
      if (epoch !== generation.current || auth.currentUser?.uid !== current.uid)
        return;
      const token = await current.getIdToken(true);
      if (epoch !== generation.current || auth.currentUser?.uid !== current.uid)
        return;
      const result = await request("/v1/account/deletion", {
        Authorization: `Bearer ${token}`,
      });
      if (epoch !== generation.current || auth.currentUser?.uid !== current.uid)
        return;
      // Retain a session-independent receipt before dropping the private app tree.
      const cleanup = clearLocal();
      setReceipt(result.receipt);
      await receiptStorage.setItem(receiptKey, result.receipt);
      await cleanup;
    },
    pollDeletion: async () => {
      if (!receipt) return;
      const epoch = generation.current;
      const uid = auth.currentUser?.uid;
      const current = () =>
        epoch === generation.current && auth.currentUser?.uid === uid;
      const result = await request("/v1/account/deletion/status", {
        "X-Deletion-Receipt": receipt,
      });
      if (!current()) return;
      if (result.status === "complete") {
        await clearLocal();
        if (!current()) return;
        lastUid.current = null;
        await signOut(auth);
        if (epoch !== generation.current) return;
        await receiptStorage.removeItem(receiptKey);
        if (epoch !== generation.current) return;
        setReceipt(null);
        setUser(null);
        setDeletionComplete(true);
      }
      return result.status;
    },
  };
}
type Account = ReturnType<typeof useAccountState>;
const Context = createContext<Account | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const value = useAccountState();
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useAuth() {
  const value = useContext(Context);
  if (!value) throw new Error("AuthProvider is missing.");
  return value;
}
