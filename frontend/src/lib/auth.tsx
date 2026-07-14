import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiError, api, type CurrentUser } from "./api";

type AuthState =
  | { kind: "loading" }
  | { kind: "anonymous" }
  | { kind: "signed_in"; user: CurrentUser };

type AuthContextValue = {
  state: AuthState;
  signInWithGoogle: (credential: string) => Promise<void>;
  signInWithPassword: (email: string, password: string) => Promise<void>;
  registerWithToken: (
    token: string,
    password: string,
    displayName?: string
  ) => Promise<void>;
  resetPasswordWithToken: (token: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
  switchTenant: (tenantId: string) => Promise<void>;
  exitSwitch: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ kind: "loading" });

  const refresh = useCallback(async () => {
    try {
      const user = await api.me();
      setState({ kind: "signed_in", user });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setState({ kind: "anonymous" });
      } else {
        setState({ kind: "anonymous" });
      }
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const signInWithGoogle = useCallback(async (credential: string) => {
    const user = await api.googleLogin(credential);
    setState({ kind: "signed_in", user });
  }, []);

  const signInWithPassword = useCallback(async (email: string, password: string) => {
    const user = await api.passwordLogin(email, password);
    setState({ kind: "signed_in", user });
  }, []);

  const registerWithToken = useCallback(
    async (token: string, password: string, displayName?: string) => {
      const user = await api.register(token, password, displayName);
      setState({ kind: "signed_in", user });
    },
    []
  );

  const resetPasswordWithToken = useCallback(async (token: string, password: string) => {
    const user = await api.resetPassword(token, password);
    setState({ kind: "signed_in", user });
  }, []);

  const signOut = useCallback(async () => {
    await api.logout();
    setState({ kind: "anonymous" });
  }, []);

  const switchTenant = useCallback(async (tenantId: string) => {
    const user = await api.switchTenant(tenantId);
    setState({ kind: "signed_in", user });
  }, []);

  const exitSwitch = useCallback(async () => {
    const user = await api.exitSwitch();
    setState({ kind: "signed_in", user });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      state,
      signInWithGoogle,
      signInWithPassword,
      registerWithToken,
      resetPasswordWithToken,
      signOut,
      refresh,
      switchTenant,
      exitSwitch,
    }),
    [
      state,
      signInWithGoogle,
      signInWithPassword,
      registerWithToken,
      resetPasswordWithToken,
      signOut,
      refresh,
      switchTenant,
      exitSwitch,
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
