import { useState } from "react";
import Library from "./Library";
import Login from "./Login";
import Reader from "./Reader";
import { clearToken, getToken } from "./lib/api";

export default function App() {
  const [signedIn, setSignedIn] = useState(() => getToken() !== null);
  const [openPaperId, setOpenPaperId] = useState<string | null>(null);

  if (!signedIn) {
    return <Login onSignedIn={() => setSignedIn(true)} />;
  }

  function signOut() {
    clearToken();
    setOpenPaperId(null);
    setSignedIn(false);
  }

  if (openPaperId) {
    return <Reader paperId={openPaperId} onBack={() => setOpenPaperId(null)} onSignOut={signOut} />;
  }
  return <Library onOpen={setOpenPaperId} onSignOut={signOut} />;
}
