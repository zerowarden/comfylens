import { useRef } from "react";

import { scopeParts } from "../../lib/format";
import { useDelayedFlag } from "../../lib/hooks";
import { useUi, type Tab } from "../../state/ui";
import { Message } from "../ui";
import Advanced from "./Advanced";
import Configs from "./Configs";
import { useStats } from "./data";
import Loras from "./Loras";
import Overview from "./Overview";
import Prompts from "./Prompts";
import Resolution from "./Resolution";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "loras", label: "LoRAs" },
  { id: "configs", label: "Configurations" },
  { id: "prompts", label: "Prompts" },
  { id: "resolution", label: "Resolution & seeds" },
  { id: "advanced", label: "Advanced" },
];

function Resizer() {
  const setWidth = useUi((s) => s.setPanelWidth);
  const start = useRef<{ x: number; width: number } | null>(null);
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      className="w-1 shrink-0 cursor-col-resize bg-zinc-200 hover:bg-sky-500 dark:bg-zinc-800"
      onMouseDown={(e) => {
        e.preventDefault();
        start.current = { x: e.clientX, width: useUi.getState().panelWidth };
        const onMove = (m: MouseEvent) => {
          if (start.current) setWidth(start.current.width + (start.current.x - m.clientX));
        };
        const onUp = () => {
          start.current = null;
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      }}
    />
  );
}

export default function AnalysisPanel() {
  const open = useUi((s) => s.panelOpen);
  const width = useUi((s) => s.panelWidth);
  const tab = useUi((s) => s.tab);
  const setTab = useUi((s) => s.setTab);
  const pool = useUi((s) => s.pool);
  const stats = useStats("name", open);
  // Only a refresh slower than 300 ms shows "Updating…", so fast ones don't flicker.
  const updating = useDelayedFlag(stats.isFetching, 300);
  if (!open) return null;
  const data = stats.data;
  const parts = data ? scopeParts(data.scope) : null;

  return (
    <>
      <Resizer />
      <aside className="flex shrink-0 flex-col" style={{ width }}>
        {/* Fixed height: neither "Updating…" nor a longer sentence moves the panel below. */}
        <div className="border-b border-zinc-200 px-3 py-2 dark:border-zinc-800">
          <div className="flex items-baseline gap-2">
            <div className="min-w-0 flex-1 truncate font-medium" title={parts?.main}>
              {parts ? parts.main : "Analyzing…"}
            </div>
            <span
              aria-hidden={!updating}
              className={`shrink-0 text-xs text-zinc-500 transition-opacity duration-200 ${
                updating ? "opacity-100" : "opacity-0"
              }`}
            >
              Updating…
            </span>
          </div>
          <div className="h-4 truncate text-xs leading-4 text-zinc-500" title={parts?.notes}>
            {parts?.notes}
          </div>
        </div>
        <nav className="flex flex-wrap gap-x-1 border-b border-zinc-200 px-2 dark:border-zinc-800">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`border-b-2 px-2 py-1.5 text-xs transition-colors duration-150 ${
                tab === t.id
                  ? "border-sky-500 text-sky-700 dark:text-sky-300"
                  : "border-transparent text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
        {/* Keyed by tab: each tab starts at the top and eases in. */}
        <div key={tab} className="min-h-0 flex-1 overflow-y-auto motion-safe:animate-panel-in">
          {tab === "loras" ? (
            <Loras />
          ) : tab === "prompts" ? (
            <Prompts />
          ) : tab === "advanced" ? (
            <Advanced />
          ) : !data ? (
            <Message>{stats.isError ? stats.error.message : "Loading…"}</Message>
          ) : tab === "overview" ? (
            <Overview data={data} />
          ) : tab === "configs" ? (
            <Configs data={data} pooled={pool} />
          ) : (
            <Resolution data={data} />
          )}
        </div>
      </aside>
    </>
  );
}
