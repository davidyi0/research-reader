// Thin fetch wrappers over the FastAPI backend. No client-side data library —
// the app is two views and a handful of endpoints, React state is enough.
export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Paper = {
  id: string;
  title: string | null;
  authors: string[] | null;
  year: number | null;
  venue: string | null;
  status: "pending" | "processing" | "ready" | "failed";
  page_count: number | null;
  last_page: number | null;
  source_url: string | null;
  error: string | null;
};

export async function listPapers(): Promise<Paper[]> {
  const res = await fetch(`${API_URL}/papers`);
  if (!res.ok) throw new Error(`Failed to list papers: ${res.status}`);
  return res.json();
}

export async function createPaper(source: string): Promise<Paper> {
  const body = new FormData();
  body.set("source", source);
  const res = await fetch(`${API_URL}/papers`, { method: "POST", body });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `Failed to add paper: ${res.status}`);
  }
  return res.json();
}

export function pdfFileUrl(paperId: string): string {
  return `${API_URL}/papers/${paperId}/file`;
}

export type ExplainHandlers = {
  onDelta: (delta: string) => void;
  onDone: () => void;
  onError: (message: string) => void;
};

// SSE via fetch + ReadableStream, not EventSource — EventSource is GET-only
// and /explain is a POST. Parses the backend's `data: {...}\n\n` framing.
export async function streamExplain(
  paperId: string,
  pageNumber: number,
  selectedText: string,
  handlers: ExplainHandlers,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/papers/${paperId}/explain`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_number: pageNumber, selected_text: selectedText }),
    });
  } catch (e) {
    handlers.onError(String(e));
    return;
  }
  if (!res.ok || !res.body) {
    const detail = await res.json().catch(() => null);
    handlers.onError(detail?.detail ?? `HTTP ${res.status}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const raw of events) {
      const line = raw.trim();
      if (!line.startsWith("data:")) continue;
      const payload = JSON.parse(line.slice("data:".length).trim());
      if (payload.delta) handlers.onDelta(payload.delta);
      else if (payload.error) handlers.onError(payload.error);
      else if (payload.done) handlers.onDone();
    }
  }
}
