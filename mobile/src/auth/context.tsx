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
import { auth, receiptStorage, sessionPersistenceReady } from "./firebase";
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
  const [ready, setReady] = useState(false);
  const [message, setMessage] = useState("");
  const [receipt, setReceipt] = useState<string | null>(null);
  const [deletionComplete, setDeletionComplete] = useState(false);
  const [accountRestricted, setAccountRestricted] = useState(false);
  const [blocked, setBlocked] = useState(false);
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
    void Promise.all([
      auth.authStateReady(),
      receiptStorage.getItem(receiptKey),
      sessionPersistenceReady,
    ])
      .then(([, saved]) => {
        if (active) {
          setUser(auth.currentUser);
          setReceipt(saved);
          setReady(true);
        }
      })
      .catch((error) => {
        if (active) setMessage(authMessage(error));
      });
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);
  async function logout() {
    setBlocked(true);
    try {
      await clearLocal();
      await signOut(auth);
      setUser(null);
      setAccountRestricted(false);
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
    const response = await fetch(apiConfig.baseUrl + path, {
      method: "POST",
      headers,
    });
    const body = await response.json();
    if (!response.ok)
      throw new ApiError(
        body.error?.message || "Retry when connected.",
        response.status,
        body.error?.code || "request_failed",
      );
    return body;
  }
  return {
    user,
    ready,
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
      setMessage("");
      await signInWithEmailAndPassword(auth, email.trim(), password);
    },
    register: async (email: string, password: string) => {
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
      const current = auth.currentUser;
      if (!current?.email) throw new Error("Sign in again.");
      await reauthenticateWithCredential(
        current,
        EmailAuthProvider.credential(current.email, password),
      );
      const token = await current.getIdToken(true);
      const result = await request("/v1/account/deletion", {
        Authorization: `Bearer ${token}`,
      });
      // Retain a session-independent receipt before dropping the private app tree.
      const cleanup = clearLocal();
      setReceipt(result.receipt);
      await receiptStorage.setItem(receiptKey, result.receipt);
      await cleanup;
    },
    pollDeletion: async () => {
      if (!receipt) return;
      const result = await request("/v1/account/deletion/status", {
        "X-Deletion-Receipt": receipt,
      });
      if (result.status === "complete") {
        await clearLocal();
        await signOut(auth);
        await receiptStorage.removeItem(receiptKey);
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
