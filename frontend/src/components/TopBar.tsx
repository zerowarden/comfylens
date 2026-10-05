import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { IndexStatusModel, LibraryInfo } from "../api/types";
import { fmtInt } from "../lib/format";
import { indexPollInterval, runLanded } from "../lib/indexing";
import { useUi } from "../state/ui";
import { Glyph } from "./icons";
import { Button, Segmented } from "./ui";

/** Poll the indexer, and refresh all data once a run lands. */
function useIndexStatus() {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["index-status"],
    queryFn: api.indexStatus,
    // Re-evaluated on every render, so it sees `watching` once the library answer arrives.
    refetchInterval: (q) =>
      indexPollInterval(
        q.state.data?.state,
        queryClient.getQueryData<LibraryInfo>(["library"])?.watching ?? false,
      ),
  });
  const library = useQuery({
    queryKey: ["library"],
    queryFn: api.library,
    // While indexing, watch for the snapshot swap that follows the run; while prompt frames
    // build, watch for frame-dependent answers (e.g. a similar-sentence filter) to become valid.
    refetchInterval: (q) =>
      q.state.data?.prompts_ready === false || (status.data && status.data.state !== "idle")
        ? 2000
        : false,
  });

  const previousStatus = useRef(status.data);
  useEffect(() => {
    if (runLanded(previousStatus.current, status.data)) {
      void queryClient.invalidateQueries({ queryKey: ["library"] });
    }
    previousStatus.current = status.data;
  }, [status.data, queryClient]);

  const builtAt = library.data?.snapshot_built_at;
  const previousBuild = useRef(builtAt);
  useEffect(() => {
    if (previousBuild.current !== undefined && builtAt !== previousBuild.current) {
      void queryClient.invalidateQueries({
        predicate: (q) => q.queryKey[0] !== "library" && q.queryKey[0] !== "index-status",
      });
    }
    previousBuild.current = builtAt;
  }, [builtAt, queryClient]);

  return { status: status.data, library: library.data };
}

function Progress({ status }: { status: IndexStatusModel }) {
  if (status.state === "idle") return null;
  const share = status.total > 0 ? status.done / status.total : 0;
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span className="capitalize">{status.state}</span>
      {status.state === "processing" && (
        <>
          <div className="h-1.5 w-40 rounded bg-track">
            <div className="h-1.5 rounded bg-accent" style={{ width: `${share * 100}%` }} />
          </div>
          <span className="tabular-nums">
            {fmtInt(status.done)} / {fmtInt(status.total)}
          </span>
        </>
      )}
      {status.errors > 0 && <span className="text-warning">{fmtInt(status.errors)} errors</span>}
    </div>
  );
}

/**
 * A sliding switch: the knob sits left with a sun in the light theme and right with a moon in the
 * dark one. Its colours are the toggle tokens in theme.css.
 */
function ThemeToggle() {
  const dark = useUi((s) => s.theme === "dark");
  const toggleTheme = useUi((s) => s.toggleTheme);
  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label="Dark theme"
      title={dark ? "Switch to the light theme" : "Switch to the dark theme"}
      onClick={toggleTheme}
      className="relative h-6 w-11 shrink-0 rounded-full bg-toggle-track shadow-inner ring-1 ring-overlay/10 transition-colors duration-200 outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      <span
        className={`absolute top-0.5 left-0.5 flex size-5 items-center justify-center rounded-full bg-toggle-knob text-toggle-icon shadow transition-transform duration-200 ${
          dark ? "translate-x-5" : ""
        }`}
      >
        <Glyph
          name={dark ? "moon" : "sun"}
          className={`size-3.5 ${dark ? "[&_path]:fill-current" : ""}`}
        />
      </span>
    </button>
  );
}

export default function TopBar() {
  const queryClient = useQueryClient();
  const { status, library } = useIndexStatus();
  const panelOpen = useUi((s) => s.panelOpen);
  const setPanelOpen = useUi((s) => s.setPanelOpen);
  const view = useUi((s) => s.view);
  const setView = useUi((s) => s.setView);
  const [notice, setNotice] = useState<string | null>(null);

  const rescan = useMutation({
    mutationFn: api.rescan,
    onSuccess: (data) => {
      setNotice(null);
      queryClient.setQueryData(["index-status"], data);
    },
    onError: (error) =>
      setNotice(
        error instanceof ApiError && error.status === 409
          ? "An index run is already in progress"
          : `Rescan failed: ${error.message}`,
      ),
  });

  const running = status !== undefined && status.state !== "idle";
  return (
    <header className="flex h-11 shrink-0 items-center gap-3 border-b border-line px-3">
      <span className="font-semibold">ComfyLens</span>
      <Segmented
        value={view}
        options={[
          { value: "library", label: "Library" },
          { value: "collection", label: "Collection" },
        ]}
        onChange={setView}
      />
      <span className="min-w-0 truncate font-mono text-xs text-muted" title={library?.root}>
        {library?.root}
      </span>
      {library && (
        <span className="text-xs text-muted tabular-nums">{fmtInt(library.total)} files</span>
      )}
      {library?.watching && (
        <span
          className="flex items-center gap-1 rounded bg-success/15 px-1.5 py-0.5 text-xs text-success"
          title="Watching the library: new and changed files are indexed automatically"
        >
          <span aria-hidden="true">●</span> watching
        </span>
      )}
      {library && library.timestamp_suspect > 0 && (
        <span
          className="rounded bg-warning/15 px-1.5 py-0.5 text-xs text-warning"
          title="Files whose modification times look like a bulk copy rather than generation"
        >
          {fmtInt(library.timestamp_suspect)} suspect timestamps
        </span>
      )}
      <div className="flex-1" />
      {status && <Progress status={status} />}
      {status?.last_error && !running && (
        <span className="max-w-64 truncate text-xs text-danger" title={status.last_error}>
          {status.last_error}
        </span>
      )}
      {notice && <span className="text-xs text-warning">{notice}</span>}
      <Button onClick={() => rescan.mutate()} disabled={running || rescan.isPending}>
        Rescan
      </Button>
      {view === "library" && (
        <Button onClick={() => setPanelOpen(!panelOpen)} title="Toggle analysis panel">
          Analysis
        </Button>
      )}
      <ThemeToggle />
    </header>
  );
}
