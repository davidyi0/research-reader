import { useEffect, useMemo, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
// Vite-friendly worker URL. Matches the installed pdfjs-dist version.
import PdfWorker from "pdfjs-dist/build/pdf.worker.min.js?url";
import { type Lens, listLenses, pdfFileUrl, streamExplain } from "./lib/api";

pdfjsLib.GlobalWorkerOptions.workerSrc = PdfWorker;

const PAGE_WIDTH = 900;
const GUTTER_WIDTH = 480;
// Below this, a mouseup is treated as an idle click/drag, not an intentional
// "explain this" selection — value not load-bearing, tune freely.
const MIN_SELECTION_CHARS = 12;

type Rect = { left: number; top: number; width: number; height: number };

type PendingSelection = {
  pageNumber: number;
  selectedText: string;
  rects: Rect[]; // page-local, for the popover
  docTop: number; // flow-relative, for popover placement
  docLeft: number;
};

type Card = {
  id: string;
  pageNumber: number;
  selectedText: string;
  rects: Rect[]; // page-local, for the tint
  docTop: number; // flow-relative, for the gutter card
  lensLabel: string;
  text: string;
  status: "streaming" | "done" | "error";
  error?: string;
};

export default function Reader({ paperId, onBack }: { paperId: string; onBack: () => void }) {
  const [numPages, setNumPages] = useState(0);
  const [scale, setScale] = useState(1);
  const [loadError, setLoadError] = useState<string | null>(null);
  const pdfDocRef = useRef<any>(null);

  const [pending, setPending] = useState<PendingSelection | null>(null);
  const [active, setActive] = useState<Card | null>(null);
  const [collapsed, setCollapsed] = useState<Card[]>([]);
  const [lenses, setLenses] = useState<Lens[]>([]);

  const flowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listLenses().then(setLenses).catch(() => setLenses([]));
  }, []);

  useEffect(() => {
    // Keep the loading task itself (not just a `cancelled` flag) so cleanup
    // can call `.destroy()` — React 18 StrictMode double-invokes this effect
    // in dev, and a bare flag leaves the first task's worker half-initialized
    // instead of properly torn down, which was hanging the second attempt.
    const loadingTask = pdfjsLib.getDocument(pdfFileUrl(paperId));
    let cancelled = false;
    loadingTask.promise
      .then(async (doc: any) => {
        if (cancelled) return;
        pdfDocRef.current = doc;
        const firstPage = await doc.getPage(1);
        const unscaled = firstPage.getViewport({ scale: 1 });
        setScale(PAGE_WIDTH / unscaled.width);
        setNumPages(doc.numPages);
      })
      .catch((e: unknown) => {
        if (!cancelled) setLoadError(String(e));
      });
    return () => {
      cancelled = true;
      loadingTask.destroy();
    };
  }, [paperId]);

  function collapseActive() {
    // Read `active` from the closure rather than setActive's functional
    // updater — calling setCollapsed as a side effect inside that updater
    // meant the tint only appeared on the *next* unrelated state change
    // (e.g. the following selection), not immediately on collapse.
    if (!active) return;
    setCollapsed((c) => [...c, { ...active, status: "done" }]);
    setActive(null);
  }

  function startExplanation(sel: PendingSelection, lens: Lens) {
    collapseActive();
    setPending(null);
    // Clear the native selection now that it's captured in the card — the
    // tint (drawn from the stored rects) takes over once this collapses, and
    // leaving the browser selection live would otherwise sit on top of it.
    window.getSelection()?.removeAllRanges();
    const card: Card = {
      id: `${Date.now()}`,
      pageNumber: sel.pageNumber,
      selectedText: sel.selectedText,
      rects: sel.rects,
      docTop: sel.docTop,
      lensLabel: lens.label,
      text: "",
      status: "streaming",
    };
    setActive(card);
    streamExplain(paperId, sel.pageNumber, sel.selectedText, lens.key, {
      onDelta: (delta) =>
        setActive((c) => (c && c.id === card.id ? { ...c, text: c.text + delta } : c)),
      onDone: () => setActive((c) => (c && c.id === card.id ? { ...c, status: "done" } : c)),
      onError: (message) =>
        setActive((c) => (c && c.id === card.id ? { ...c, status: "error", error: message } : c)),
    });
  }

  function reopenCard(id: string) {
    const hit = collapsed.find((c) => c.id === id);
    if (!hit) return;
    collapseActive();
    setCollapsed((cs) => cs.filter((c) => c.id !== id));
    setActive(hit);
  }

  function handleMouseUp(e: React.MouseEvent) {
    const flow = flowRef.current;
    if (!flow) return;
    const flowRect = flow.getBoundingClientRect();
    const sel = window.getSelection();
    // Only treat this as a new selection if the mouseup actually happened
    // over page text — otherwise a stale (already-consumed) window selection
    // re-triggers this branch on any later click elsewhere, e.g. the card's
    // "x" button, producing a duplicate popover for text no longer selected.
    const inTextLayer = !!(e.target as HTMLElement).closest(".textLayer");

    if (inTextLayer && sel && !sel.isCollapsed && sel.toString().trim().length >= MIN_SELECTION_CHARS) {
      const range = sel.getRangeAt(0);
      const pageEl = (range.startContainer.parentElement as HTMLElement | null)?.closest(
        "[data-page]",
      ) as HTMLElement | null;
      if (!pageEl) return;
      const pageNumber = Number(pageEl.dataset.page);
      const pageRect = pageEl.getBoundingClientRect();
      const clientRects = Array.from(range.getClientRects());
      if (clientRects.length === 0) return;
      const rects = clientRects.map((r) => ({
        left: r.left - pageRect.left,
        top: r.top - pageRect.top,
        width: r.width,
        height: r.height,
      }));
      setPending({
        pageNumber,
        selectedText: sel.toString().trim(),
        rects,
        docTop: clientRects[0].top - flowRect.top + flow.scrollTop,
        docLeft: clientRects[clientRects.length - 1].right - flowRect.left + flow.scrollLeft,
      });
      return;
    }

    // Collapsed click: either dismiss the pending popover, or reopen a tint.
    // Only act on clicks that actually land on a page — a click on our own
    // floating chrome (the popover's Simplify button, a card's close button)
    // isn't a page interaction, and clearing `pending` here would unmount
    // the popover out from under its own onClick before it can fire.
    const target = e.target as HTMLElement;
    const pageEl = target.closest("[data-page]") as HTMLElement | null;
    if (!pageEl) return;
    setPending(null);
    const pageNumber = Number(pageEl.dataset.page);
    const pageRect = pageEl.getBoundingClientRect();
    const x = e.clientX - pageRect.left;
    const y = e.clientY - pageRect.top;
    const hit = collapsed.find(
      (c) =>
        c.pageNumber === pageNumber &&
        c.rects.some((r) => x >= r.left && x <= r.left + r.width && y >= r.top && y <= r.top + r.height),
    );
    if (hit) reopenCard(hit.id);
  }

  const collapsedByPage = useMemo(() => {
    const map = new Map<number, Card[]>();
    for (const c of collapsed) {
      map.set(c.pageNumber, [...(map.get(c.pageNumber) ?? []), c]);
    }
    return map;
  }, [collapsed]);

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-4 border-b border-slate-200 px-4 py-2">
        <button onClick={onBack} className="text-sm text-slate-500 hover:text-slate-800">
          ← Library
        </button>
      </header>

      {loadError && <p className="p-4 text-sm text-red-600">Could not load PDF: {loadError}</p>}

      <div
        ref={flowRef}
        onMouseUp={handleMouseUp}
        className="relative flex flex-1 justify-center gap-8 overflow-y-auto bg-slate-100 py-8"
      >
        {/* Plain block stacking, not flex: every PageView child is absolutely
            positioned (canvas/tint/text layers), so a flex column here has no
            in-flow content to size against and collapses each item's explicit
            height. Margin-based stacking sidesteps that entirely. */}
        <div style={{ width: PAGE_WIDTH }}>
          {scale > 0 &&
            Array.from({ length: numPages }, (_, i) => i + 1).map((n) => (
              <PageView
                key={n}
                pdfDoc={pdfDocRef.current}
                pageNumber={n}
                scale={scale}
                tints={collapsedByPage.get(n) ?? []}
              />
            ))}
        </div>

        <div className="relative" style={{ width: GUTTER_WIDTH }}>
          {active && (
            <ExplanationCard
              card={active}
              onClose={collapseActive}
              style={{ position: "absolute", top: active.docTop, width: GUTTER_WIDTH }}
            />
          )}
        </div>

        {pending && lenses.length > 0 && (
          <div
            className="absolute z-10 flex flex-col gap-0.5 rounded-md bg-slate-800 p-1 shadow-lg"
            style={{ top: pending.docTop, left: pending.docLeft }}
          >
            {lenses.map((lens) => (
              <button
                key={lens.key}
                onClick={() => startExplanation(pending, lens)}
                className="whitespace-nowrap rounded px-3 py-1 text-left text-xs font-medium text-white hover:bg-slate-700"
              >
                {lens.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PageView({
  pdfDoc,
  pageNumber,
  scale,
  tints,
}: {
  pdfDoc: any;
  pageNumber: number;
  scale: number;
  tints: Card[];
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textLayerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: PAGE_WIDTH, height: PAGE_WIDTH * 1.3 });

  useEffect(() => {
    if (!pdfDoc) return;
    let cancelled = false;
    // pdf.js throws "Cannot use the same canvas during multiple render()
    // operations" if a second render starts before the first is torn down —
    // which is exactly what React 18 StrictMode's dev-mode double-invoke
    // does. Track both tasks so cleanup can cancel them explicitly.
    let renderTask: { cancel: () => void; promise: Promise<unknown> } | null = null;
    let textLayerTask: { cancel: () => void; promise: Promise<unknown> } | null = null;

    pdfDoc.getPage(pageNumber).then(async (page: any) => {
      if (cancelled) return;
      const viewport = page.getViewport({ scale });
      setSize({ width: viewport.width, height: viewport.height });

      const canvas = canvasRef.current;
      if (canvas) {
        // Render at device pixel density, not just CSS pixels — otherwise
        // the canvas backing store is 1:1 with CSS px and looks blurry on
        // any HiDPI display once the browser upscales it.
        const dpr = window.devicePixelRatio || 1;
        canvas.width = viewport.width * dpr;
        canvas.height = viewport.height * dpr;
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        const ctx = canvas.getContext("2d")!;
        ctx.scale(dpr, dpr);
        renderTask = page.render({ canvasContext: ctx, viewport });
        await renderTask!.promise.catch(() => {});
      }
      if (cancelled) return;

      const textLayerDiv = textLayerRef.current;
      if (textLayerDiv) {
        textLayerDiv.innerHTML = "";
        textLayerDiv.style.width = `${viewport.width}px`;
        textLayerDiv.style.height = `${viewport.height}px`;
        // pdf.js scales each span via `calc(var(--scale-factor) * ...)`; without
        // this set explicitly the calc is invalid and spans fall back to
        // untransformed static layout instead of sitting over the glyphs.
        textLayerDiv.style.setProperty("--scale-factor", String(scale));
        const textContent = await page.getTextContent();
        if (cancelled) return;
        textLayerTask = pdfjsLib.renderTextLayer({
          textContentSource: textContent,
          container: textLayerDiv,
          viewport,
        });
        await textLayerTask!.promise.catch(() => {});
      }
    });
    return () => {
      cancelled = true;
      renderTask?.cancel();
      textLayerTask?.cancel();
    };
  }, [pdfDoc, pageNumber, scale]);

  return (
    <div
      data-page={pageNumber}
      className="relative mb-4 bg-white shadow"
      style={{ width: size.width, height: size.height }}
    >
      <canvas ref={canvasRef} className="absolute inset-0" />
      {/* Tint layer: between canvas and text layer, per the locked spec —
          rendered as its own divs from getClientRects(), not text-layer-span
          backgrounds, since those are scaled approximations that render offset. */}
      <div className="pointer-events-none absolute inset-0">
        {tints.map((card) =>
          card.rects.map((r, i) => (
            <div
              key={`${card.id}-${i}`}
              className="absolute bg-amber-200/50"
              style={{ left: r.left, top: r.top, width: r.width, height: r.height }}
            />
          )),
        )}
      </div>
      <div ref={textLayerRef} className="textLayer" />
    </div>
  );
}

function ExplanationCard({
  card,
  onClose,
  style,
}: {
  card: Card;
  onClose: () => void;
  style: React.CSSProperties;
}) {
  return (
    <div style={style} className="rounded-md border border-slate-200 bg-white p-4 shadow-md">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            {card.lensLabel}
          </p>
          <p className="line-clamp-2 text-xs italic text-slate-400">"{card.selectedText}"</p>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
          ×
        </button>
      </div>
      <div className="mt-2 text-sm leading-relaxed text-slate-800">
        {card.text}
        {card.status === "streaming" && <span className="animate-pulse">▍</span>}
      </div>
      {card.status === "error" && (
        <p className="mt-2 text-xs text-red-600">{card.error ?? "Something went wrong."}</p>
      )}
    </div>
  );
}
