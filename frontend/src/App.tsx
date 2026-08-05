import { useState } from "react";
import Library from "./Library";
import Reader from "./Reader";

export default function App() {
  const [openPaperId, setOpenPaperId] = useState<string | null>(null);

  if (openPaperId) {
    return <Reader paperId={openPaperId} onBack={() => setOpenPaperId(null)} />;
  }
  return <Library onOpen={setOpenPaperId} />;
}
