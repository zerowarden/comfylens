import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { IndexStatusModel, LibraryInfo } from "../api/types";
import { fmtInt } from "../lib/format";
import { indexPollInterval, runLanded } from "../lib/indexing";
import { useUi } from "../state/ui";
import { Button } from "./ui";

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
    // While indexing, watch for the snapshot swap that follows the run.
    refetchInterval: status.data && status.data.state !== "idle" ? 2000 : false,
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
    <div className="flex items-center gap-2 text-xs text-zinc-500">
      <span className="capitalize">{status.state}</span>
      {status.state === "processing" && (
        <>
          <div className="h-1.5 w-40 rounded bg-zinc-200 dark:bg-zinc-800">
            <div className="h-1.5 rounded bg-sky-500" style={{ width: `${share * 100}%` }} />
          </div>
          <span className="tabular-nums">
            {fmtInt(status.done)} / {fmtInt(status.total)}
          </span>
        </>
      )}
      {status.errors > 0 && <span className="text-amber-600">{fmtInt(status.errors)} errors</span>}
    </div>
  );
}

export default function TopBar() {
  const queryClient = useQueryClient();
  const { status, library } = useIndexStatus();
  const pool = useUi((s) => s.pool);
  const setPool = useUi((s) => s.setPool);
  const theme = useUi((s) => s.theme);
  const toggleTheme = useUi((s) => s.toggleTheme);
  const sidebarOpen = useUi((s) => s.sidebarOpen);
  const setSidebarOpen = useUi((s) => s.setSidebarOpen);
  const panelOpen = useUi((s) => s.panelOpen);
  const setPanelOpen = useUi((s) => s.setPanelOpen);
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
    <header className="flex h-11 shrink-0 items-center gap-3 border-b border-zinc-200 px-3 dark:border-zinc-800">
      <Button onClick={() => setSidebarOpen(!sidebarOpen)} title="Toggle filters">
        ☰
      </Button>
      <span className="font-semibold">ComfyLens</span>
      <span className="min-w-0 truncate font-mono text-xs text-zinc-500" title={library?.root}>
        {library?.root}
      </span>
      {library && (
        <span className="text-xs text-zinc-500 tabular-nums">{fmtInt(library.total)} files</span>
      )}
      {library?.watching && (
        <span
          className="flex items-center gap-1 rounded bg-emerald-500/15 px-1.5 py-0.5 text-xs text-emerald-700 dark:text-emerald-300"
          title="Watching the library: new and changed files are indexed automatically"
        >
          <span aria-hidden="true">●</span> watching
        </span>
      )}
      {library && library.timestamp_suspect > 0 && (
        <span
          className="rounded bg-amber-500/15 px-1.5 py-0.5 text-xs text-amber-700 dark:text-amber-300"
          title="Files whose modification times look like a bulk copy rather than generation"
        >
          {fmtInt(library.timestamp_suspect)} suspect timestamps
        </span>
      )}
      <div className="flex-1" />
      {status && <Progress status={status} />}
      {status?.last_error && !running && (
        <span className="max-w-64 truncate text-xs text-red-600" title={status.last_error}>
          {status.last_error}
        </span>
      )}
      {notice && <span className="text-xs text-amber-600">{notice}</span>}
      <Button onClick={() => rescan.mutate()} disabled={running || rescan.isPending}>
        Rescan
      </Button>
      <Button
        active={pool}
        onClick={() => setPool(!pool)}
        title="Compute one group across families"
      >
        Pool families
      </Button>
      <Button onClick={toggleTheme} title="Toggle theme">
        {theme === "dark" ? "Light" : "Dark"}
      </Button>
      <Button onClick={() => setPanelOpen(!panelOpen)} title="Toggle analysis panel">
        Analysis
      </Button>
    </header>
  );
}
