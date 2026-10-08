import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { IndexStatusModel, LibraryInfo } from "../api/types";
import { fmtInt } from "../lib/format";
import { fixNotice, indexPollInterval, runLanded } from "../lib/indexing";
import { useFileActions } from "../state/fileActions";
import { useUi } from "../state/ui";
import { Glyph } from "./icons";
import { Modal } from "./Modal";
import { Button, DialogActions, PRIMARY, Segmented, ShareBar } from "./ui";

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

/** States that count files: the bar shows how many are done. */
const COUNTED = new Set<IndexStatusModel["state"]>(["fixing", "processing"]);

function Progress({ status }: { status: IndexStatusModel }) {
  if (status.state === "idle") return null;
  const share = status.total > 0 ? status.done / status.total : 0;
  return (
    <div className="flex items-center gap-2 text-xs text-muted motion-safe:animate-fade-in">
      <span className="capitalize">{status.state}</span>
      {COUNTED.has(status.state) && (
        <>
          <ShareBar share={share} className="w-40" />
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

/** The library's root and size, and badges for watch mode and suspect timestamps. */
function LibraryBadges({ library }: { library: LibraryInfo }) {
  return (
    <>
      <span className="min-w-0 truncate font-mono text-xs text-muted" title={library.root}>
        {library.root}
      </span>
      <span className="text-xs text-muted tabular-nums">{fmtInt(library.total)} files</span>
      {library.watching && (
        <span
          className="flex items-center gap-1 rounded bg-success/15 px-1.5 py-0.5 text-xs text-success"
          title="Watching the library: new and changed files are indexed automatically"
        >
          <span aria-hidden="true">●</span> watching
        </span>
      )}
      {library.timestamp_suspect > 0 && (
        <span
          className="rounded bg-warning/15 px-1.5 py-0.5 text-xs text-warning"
          title="Files whose modification times look like a bulk copy rather than generation"
        >
          {fmtInt(library.timestamp_suspect)} suspect timestamps
        </span>
      )}
    </>
  );
}

const runError = (action: string, error: Error) =>
  error instanceof ApiError && error.status === 409
    ? "An index run is already in progress"
    : `${action} failed: ${error.message}`;

/** Report each Fix run once it has landed: its files re-read and the new data served. */
function useFixNotice(status: IndexStatusModel | undefined) {
  const notify = useFileActions((s) => s.notify);
  const seen = useRef<number | null | undefined>(undefined);
  const fix = status?.last_fix ?? null;
  useEffect(() => {
    if (!status || status.state !== "idle") return;
    const finished = fix?.finished_at ?? null;
    // The first answer only sets what was already known: a run from before the page loaded.
    if (seen.current !== undefined && fix && finished !== seen.current) notify(fixNotice(fix));
    seen.current = finished;
  }, [status, fix, notify]);
}

/** The Fix button, and the confirmation it asks for: files are rewritten in place. */
function FixButton({
  busy,
  onError,
}: {
  busy: boolean;
  onError: (message: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const fix = useMutation({
    mutationFn: api.fix,
    onSuccess: (data) => {
      onError(null);
      queryClient.setQueryData(["index-status"], data);
    },
    onError: (error) => onError(runError("Fix", error)),
  });
  const close = () => setConfirming(false);
  return (
    <>
      <Button
        onClick={() => setConfirming(true)}
        disabled={busy || fix.isPending}
        title="Rewrite the library's image metadata to fix known problems"
      >
        Fix
      </Button>
      {confirming && (
        <Modal title="Fix the library?" onClose={close}>
          <p className="mb-2 text-sm">
            Rewrites the metadata of images that name LoRAs which cannot affect them: connected to
            nothing, or switched off in a Power Lora Loader. Those LoRAs leave the prompt and the
            workflow.
          </p>
          <p className="mb-4 text-xs text-muted">
            The files are changed in place, PNG only. Pixels, tags and modification times stay, and
            saved prompts keep their links. There is no undo.
          </p>
          <DialogActions>
            <Button onClick={close}>Cancel</Button>
            <button
              type="button"
              autoFocus
              className={PRIMARY}
              onClick={() => {
                close();
                fix.mutate();
              }}
            >
              Fix
            </button>
          </DialogActions>
        </Modal>
      )}
    </>
  );
}

/** Indexing progress, the last run's error, and the Rescan and Fix buttons. */
function Indexing({ status }: { status: IndexStatusModel | undefined }) {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  useFixNotice(status);
  const rescan = useMutation({
    mutationFn: api.rescan,
    onSuccess: (data) => {
      setNotice(null);
      queryClient.setQueryData(["index-status"], data);
    },
    onError: (error) => setNotice(runError("Rescan", error)),
  });
  const running = status !== undefined && status.state !== "idle";
  const lastError = running ? null : status?.last_error;
  return (
    <>
      {status && <Progress status={status} />}
      {lastError && (
        <span className="max-w-64 truncate text-xs text-danger" title={lastError}>
          {lastError}
        </span>
      )}
      {notice && <span className="text-xs text-warning">{notice}</span>}
      <Button onClick={() => rescan.mutate()} disabled={running || rescan.isPending}>
        Rescan
      </Button>
      <FixButton busy={running} onError={setNotice} />
    </>
  );
}

export default function TopBar() {
  const { status, library } = useIndexStatus();
  const panelOpen = useUi((s) => s.panelOpen);
  const setPanelOpen = useUi((s) => s.setPanelOpen);
  const view = useUi((s) => s.view);
  const setView = useUi((s) => s.setView);
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
      {library && <LibraryBadges library={library} />}
      <div className="flex-1" />
      <Indexing status={status} />
      {view === "library" && (
        <Button onClick={() => setPanelOpen(!panelOpen)} title="Toggle analysis panel">
          Analysis
        </Button>
      )}
      <ThemeToggle />
    </header>
  );
}
