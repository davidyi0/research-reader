import { FormEvent, useEffect, useState } from "react";
import { Paper, createPaper, listPapers } from "./lib/api";

export default function Library({ onOpen }: { onOpen: (paperId: string) => void }) {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [source, setSource] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setPapers(await listPapers());
  }

  useEffect(() => {
    refresh().catch((e) => setError(String(e)));
  }, []);

  // Any paper still processing needs its status polled so it flips to
  // ready/failed without a manual refresh.
  useEffect(() => {
    if (!papers.some((p) => p.status === "processing" || p.status === "pending")) return;
    const id = setInterval(() => refresh().catch(() => {}), 2000);
    return () => clearInterval(id);
  }, [papers]);

  async function handleAdd(e: FormEvent) {
    e.preventDefault();
    if (!source.trim()) return;
    setAdding(true);
    setError(null);
    try {
      await createPaper(source.trim());
      setSource("");
      await refresh();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <h1 className="text-2xl font-bold text-slate-800">Library</h1>

      <form onSubmit={handleAdd} className="mt-6 flex gap-2">
        <input
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="arXiv ID/URL, DOI, or PDF URL"
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={adding}
          className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {adding ? "Adding…" : "Add"}
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

      <ul className="mt-8 divide-y divide-slate-200">
        {papers.map((p) => (
          <li key={p.id} className="py-3">
            <button
              onClick={() => p.status === "ready" && onOpen(p.id)}
              disabled={p.status !== "ready"}
              className="w-full text-left disabled:cursor-not-allowed"
            >
              <div className="font-medium text-slate-800">
                {p.title ?? p.source_url ?? "Untitled"}
              </div>
              <div className="mt-0.5 text-xs text-slate-500">
                {p.status === "ready" && `${p.page_count ?? "?"} pages`}
                {p.status === "processing" && "Processing…"}
                {p.status === "pending" && "Queued…"}
                {p.status === "failed" && (
                  <span className="text-red-600">{p.error ?? "Failed to process."}</span>
                )}
              </div>
            </button>
          </li>
        ))}
        {papers.length === 0 && <p className="py-6 text-sm text-slate-400">No papers yet.</p>}
      </ul>
    </div>
  );
}
