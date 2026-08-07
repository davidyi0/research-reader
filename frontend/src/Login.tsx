import { useEffect, useRef, useState } from "react";
import { setToken, signInWithGoogle } from "./lib/api";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;

// Minimal typing for the bits of Google Identity Services we actually call.
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (resp: { credential: string }) => void;
          }) => void;
          renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
        };
      };
    };
  }
}

export default function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const buttonRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;

    async function handleCredential(resp: { credential: string }) {
      try {
        const session = await signInWithGoogle(resp.credential);
        setToken(session.token);
        onSignedIn();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }

    // The GSI script self-registers on window.google; loaded once here rather
    // than in index.html so this component works standalone.
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => {
      if (!window.google || !buttonRef.current) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleCredential,
      });
      window.google.accounts.id.renderButton(buttonRef.current, {
        theme: "outline",
        size: "large",
      });
    };
    document.body.appendChild(script);
    return () => {
      document.body.removeChild(script);
    };
  }, []);

  return (
    <div className="flex h-screen items-center justify-center bg-slate-50">
      <div className="text-center">
        <h1 className="text-2xl font-bold text-slate-800">StudyLens</h1>
        <p className="mt-2 text-sm text-slate-500">Sign in to open your library.</p>
        <div className="mt-6 flex justify-center">
          {GOOGLE_CLIENT_ID ? (
            <div ref={buttonRef} />
          ) : (
            <p className="max-w-xs text-xs text-red-600">
              VITE_GOOGLE_CLIENT_ID isn't set — add it to .env and restart the frontend
              container.
            </p>
          )}
        </div>
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </div>
    </div>
  );
}
