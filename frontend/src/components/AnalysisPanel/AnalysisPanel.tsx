import type { UseQueryResult } from "@tanstack/react-query";
import { useLayoutEffect, useRef, type ComponentType } from "react";

import type { StatsResponse } from "../../api/types";
import { loadingText, scopeParts } from "../../lib/format";
import { useDelayedFlag } from "../../lib/hooks";
import { useUi, type Tab } from "../../state/ui";
import { Message } from "../ui";
import Configs from "./Configs";
import { useStats } from "./data";
import Loras from "./Loras";
import Overview from "./Overview";
import Prompts from "./Prompts";
import Resolution from "./Resolution";
import Tags from "./Tags";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "tags", label: "Tags" },
  { id: "loras", label: "LoRAs" },
  { id: "configs", label: "Configurations" },
  { id: "prompts", label: "Prompts" },
  { id: "resolution", label: "Resolution & seeds" },
];

function Resizer() {
  const setWidth = useUi((s) => s.setPanelWidth);
  const start = useRef<{ x: number; width: number } | null>(null);
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      className="w-1 shrink-0 cursor-col-resize bg-track hover:bg-accent"
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

/** Tabs that query their own data. */
const OWN_DATA = { loras: Loras, prompts: Prompts } satisfies Partial<Record<Tab, ComponentType>>;
type OwnDataTab = keyof typeof OWN_DATA;
/** Tabs drawn from the panel's statistics. */
const FROM_STATS = {
  overview: Overview,
  tags: Tags,
  configs: Configs,
  resolution: Resolution,
} satisfies Record<Exclude<Tab, OwnDataTab>, ComponentType<{ data: StatsResponse }>>;

const ownsData = (tab: Tab): tab is OwnDataTab => tab in OWN_DATA;

function TabBody({ tab, stats }: { tab: Tab; stats: UseQueryResult<StatsResponse> }) {
  if (ownsData(tab)) {
    const Own = OWN_DATA[tab];
    return <Own />;
  }
  if (!stats.data) return <Message>{loadingText(stats.error)}</Message>;
  const Body = FROM_STATS[tab];
  return <Body data={stats.data} />;
}

/** What the panel analyzes, and "Updating…" while a slow refresh runs. Fixed height: neither
 * "Updating…" nor a longer sentence moves the panel below. */
function PanelHeader({ data, updating }: { data?: StatsResponse; updating: boolean }) {
  const parts = data && scopeParts(data.scope);
  return (
    <div className="border-b border-line px-3 py-2">
      <div className="flex items-baseline gap-2">
        <div className="min-w-0 flex-1 truncate font-medium" title={parts?.main}>
          {parts?.main ?? "Analyzing…"}
        </div>
        <span
          aria-hidden={!updating}
          className={`shrink-0 text-xs text-muted transition-opacity duration-200 ${
            updating ? "opacity-100" : "opacity-0"
          }`}
        >
          Updating…
        </span>
      </div>
      <div className="h-4 truncate text-xs leading-4 text-muted" title={parts?.notes}>
        {parts?.notes}
      </div>
    </div>
  );
}

function TabBar() {
  const tab = useUi((s) => s.tab);
  const setTab = useUi((s) => s.setTab);
  return (
    <nav className="flex flex-wrap gap-x-1 border-b border-line px-2">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => setTab(t.id)}
          className={`border-b-2 px-2 py-1.5 text-xs transition-colors duration-150 ${
            tab === t.id
              ? "border-accent text-accent-text"
              : "border-transparent text-muted hover:text-fg"
          }`}
        >
          {t.label}
        </button>
      ))}
    </nav>
  );
}

/** The narrowest the tab contents lay out at; their widest tables need about this much. */
const CONTENT_MIN = 480;

export default function AnalysisPanel() {
  const open = useUi((s) => s.panelOpen);
  const width = useUi((s) => s.panelWidth);
  const tab = useUi((s) => s.tab);
  const fitWidth = useUi((s) => s.fitPanelWidth);
  const stats = useStats("name", open);
  // Only a refresh slower than 300 ms shows "Updating…", so fast ones don't flicker.
  const updating = useDelayedFlag(stats.isFetching, 300);
  const body = useRef<HTMLDivElement>(null);
  const ready = stats.data !== undefined;
  // Once the first analysis is laid out, widen the panel to what it needs to show without sideways
  // scrolling, vertical scrollbar included. Before paint, so the scrollbar never flashes.
  useLayoutEffect(() => {
    const el = body.current;
    if (ready && el) fitWidth(el.scrollWidth - el.clientWidth);
  }, [ready, fitWidth]);
  if (!open) return null;

  return (
    <>
      <Resizer />
      <aside className="flex shrink-0 flex-col" style={{ width }}>
        <PanelHeader data={stats.data} updating={updating} />
        <TabBar />
        {/* Keyed by tab: each tab starts at the top and eases in. Below CONTENT_MIN the tab keeps
            its layout and scrolls sideways rather than squeezing. */}
        <div
          key={tab}
          ref={body}
          className="min-h-0 flex-1 overflow-auto motion-safe:animate-panel-in"
        >
          <div style={{ minWidth: CONTENT_MIN }}>
            <TabBody tab={tab} stats={stats} />
          </div>
        </div>
      </aside>
    </>
  );
}
