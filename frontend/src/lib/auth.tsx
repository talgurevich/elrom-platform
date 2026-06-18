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
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
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

  const signOut = useCallback(async () => {
    await api.logout();
    setState({ kind: "anonymous" });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ state, signInWithGoogle, signOut, refresh }),
    [state, signInWithGoogle, signOut, refresh]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
