import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";

// No StrictMode: its dev-mode double-invoke of effects races pdf.js's
// imperative `canvas.render()`/worker calls (two renders on the same canvas
// throw "Cannot use the same canvas during multiple render() operations").
// Common, expected tradeoff for canvas-heavy libraries; doesn't affect prod.
createRoot(document.getElementById("root")!).render(<App />);
