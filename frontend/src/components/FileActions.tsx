import { useQueryClient } from "@tanstack/react-query";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type SubmitEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { saveImageToCollection } from "../lib/collection";
import { cachedRelPath, exportStripped, renameImage, trashImages } from "../lib/fileActions";
import { baseName, extension, nameProblem } from "../lib/files";
import { fmtInt, loadingText } from "../lib/format";
import { keepKeys } from "../lib/hooks";
import { useImageDetail } from "../lib/images";
import { useCollection } from "../state/collection";
import { useFileActions, type ContextMenu } from "../state/fileActions";
import { Glyph } from "./icons";
import { Modal } from "./Modal";
import { Button, DESTRUCTIVE, DialogActions, FOCUS_FIELD, PRIMARY } from "./ui";

const TRASH_LISTED = 5; // file names the trash dialog lists before "and N more"

/** The right-click menu on images, its rename and trash dialogs, and the notice of outcomes. */
export default function FileActions() {
  const menu = useFileActions((s) => s.menu);
  const dialog = useFileActions((s) => s.dialog);
  return (
    <>
      {menu && <Menu menu={menu} />}
      {dialog?.kind === "rename" && <RenameDialog key={dialog.id} id={dialog.id} />}
      {dialog?.kind === "trash" && <TrashDialog ids={dialog.ids} />}
      <NoticeBar />
    </>
  );
}

function Menu({ menu }: { menu: ContextMenu }) {
  const client = useQueryClient();
  const closeMenu = useFileActions((s) => s.closeMenu);
  const openDialog = useFileActions((s) => s.openDialog);
  const openLinking = useCollection((s) => s.openLinking);
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: menu.x, top: menu.y });

  // Keep the whole menu on screen, then focus its first item for the keyboard.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    setPosition({
      left: Math.max(4, Math.min(menu.x, window.innerWidth - width - 4)),
      top: Math.max(4, Math.min(menu.y, window.innerHeight - height - 4)),
    });
    el.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
  }, [menu]);

  useEffect(() => {
    window.addEventListener("blur", closeMenu);
    window.addEventListener("resize", closeMenu);
    return () => {
      window.removeEventListener("blur", closeMenu);
      window.removeEventListener("resize", closeMenu);
    };
  }, [closeMenu]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    keepKeys(e);
    if (e.key === "Escape" || e.key === "Tab") {
      e.preventDefault();
      closeMenu();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const items = [...(ref.current?.querySelectorAll("button:not(:disabled)") ?? [])];
      const step = e.key === "ArrowDown" ? 1 : -1;
      const at = items.indexOf(document.activeElement as Element);
      (items[(at + step + items.length) % items.length] as HTMLElement | undefined)?.focus();
    }
  };

  const many = menu.ids.length > 1;
  return (
    // Clicks outside close the menu without reaching the grid underneath.
    <div
      className="fixed inset-0 z-[60]"
      onClick={closeMenu}
      onWheel={closeMenu}
      onContextMenu={(e) => {
        e.preventDefault();
        closeMenu();
      }}
    >
      <div
        ref={ref}
        role="menu"
        aria-label={many ? `${fmtInt(menu.ids.length)} images` : "Image"}
        onClick={(e) => e.stopPropagation()}
        onContextMenu={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
        onKeyDown={onKeyDown}
        style={position}
        className="absolute min-w-48 rounded-md border border-control bg-surface py-1 text-sm shadow-lg"
      >
        <MenuItem
          disabled={many}
          title={many ? "Select a single image to rename it" : undefined}
          onSelect={() => openDialog({ kind: "rename", id: menu.ids[0]! })}
        >
          Rename…
        </MenuItem>
        <MenuItem
          disabled={many}
          title={
            many
              ? "Select a single image to export it"
              : "Download a copy with the same pixels and no metadata: no prompt, workflow or EXIF. The original is not changed."
          }
          onSelect={() => {
            closeMenu();
            void exportStripped(client, menu.ids[0]!);
          }}
        >
          Export without metadata
        </MenuItem>
        <MenuItem
          disabled={many}
          title={many ? "Select a single image to save it as a new prompt" : undefined}
          onSelect={() => {
            closeMenu();
            void saveImageToCollection(menu.ids[0]!);
          }}
        >
          Save to collection…
        </MenuItem>
        <MenuItem
          onSelect={() => {
            closeMenu();
            openLinking(menu.ids);
          }}
        >
          {many
            ? `Add ${fmtInt(menu.ids.length)} images to a saved prompt…`
            : "Add to saved prompt…"}
        </MenuItem>
        <MenuItem danger onSelect={() => openDialog({ kind: "trash", ids: menu.ids })}>
          {many ? `Move ${fmtInt(menu.ids.length)} images to trash…` : "Move to trash…"}
        </MenuItem>
      </div>
    </div>
  );
}

function MenuItem({
  children,
  onSelect,
  disabled = false,
  danger = false,
  title,
}: {
  children: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  danger?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      title={title}
      onClick={onSelect}
      className={`block w-full px-3 py-1 text-left outline-none hover:bg-hover focus:bg-hover disabled:opacity-40 disabled:hover:bg-transparent ${
        danger ? "text-danger" : ""
      }`}
    >
      {children}
    </button>
  );
}

function RenameDialog({ id }: { id: number }) {
  const client = useQueryClient();
  const openDialog = useFileActions((s) => s.openDialog);
  // The right-clicked tile's page is cached; ask the server only when it is not.
  const cached = useMemo(() => cachedRelPath(client, id), [client, id]);
  const detail = useImageDetail(id, cached === null);
  const relPath = cached ?? detail.data?.file.rel_path ?? null;
  const close = () => openDialog(null);
  return (
    <Modal title="Rename image" onClose={close}>
      {relPath === null ? (
        <p className="text-sm text-muted">{loadingText(detail.error)}</p>
      ) : (
        <RenameForm
          relPath={relPath}
          onCancel={close}
          onRename={(name) => {
            close();
            void renameImage(client, id, relPath, name);
          }}
        />
      )}
    </Modal>
  );
}

function RenameForm({
  relPath,
  onCancel,
  onRename,
}: {
  relPath: string;
  onCancel: () => void;
  onRename: (name: string) => void;
}) {
  const current = baseName(relPath);
  const directory = relPath.slice(0, relPath.length - current.length);
  const [name, setName] = useState(current);
  const problem = name === current ? null : nameProblem(current, name);
  const input = useRef<HTMLInputElement>(null);

  // Select the name without its extension, as file managers do.
  useEffect(() => {
    input.current?.focus();
    input.current?.setSelectionRange(0, current.length - extension(current).length);
  }, [current]);

  const submit = (e: SubmitEvent) => {
    e.preventDefault();
    if (name === current) onCancel();
    else if (!problem) onRename(name);
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <label className="block text-xs text-muted">
        New name
        {directory && (
          <>
            {" "}
            in <span className="font-mono break-all">{directory}</span>
          </>
        )}
        <input
          ref={input}
          value={name}
          onChange={(e) => setName(e.target.value)}
          spellCheck={false}
          autoComplete="off"
          aria-invalid={problem !== null}
          className={`mt-1 block w-full px-2 py-1 font-mono text-sm ${FOCUS_FIELD}`}
        />
      </label>
      {problem && <p className="text-xs text-danger">{problem}</p>}
      <DialogActions>
        <Button onClick={onCancel}>Cancel</Button>
        <button type="submit" disabled={problem !== null} className={PRIMARY}>
          Rename
        </button>
      </DialogActions>
    </form>
  );
}

function TrashDialog({ ids }: { ids: number[] }) {
  const client = useQueryClient();
  const openDialog = useFileActions((s) => s.openDialog);
  const listed = useMemo(
    () => ids.slice(0, TRASH_LISTED).map((id) => [id, cachedRelPath(client, id)] as const),
    [client, ids],
  );
  const close = () => openDialog(null);
  const title =
    ids.length === 1
      ? "Move this image to the trash?"
      : `Move ${fmtInt(ids.length)} images to the trash?`;
  return (
    <Modal title={title} onClose={close}>
      <ul className="mb-3 space-y-0.5 font-mono text-xs break-all text-soft">
        {listed.map(([id, relPath]) => (
          <li key={id}>{relPath ?? `image ${id}`}</li>
        ))}
        {ids.length > TRASH_LISTED && (
          <li className="font-sans text-muted">and {fmtInt(ids.length - TRASH_LISTED)} more</li>
        )}
      </ul>
      <p className="mb-4 text-xs text-muted">
        The files go to the system trash, where your file manager can restore them.
      </p>
      <DialogActions>
        <Button onClick={close}>Cancel</Button>
        <button
          type="button"
          autoFocus
          onClick={() => {
            close();
            void trashImages(client, ids);
          }}
          className={DESTRUCTIVE}
        >
          Move to trash
        </button>
      </DialogActions>
    </Modal>
  );
}

function NoticeBar() {
  const notice = useFileActions((s) => s.notice);
  const notify = useFileActions((s) => s.notify);
  useEffect(() => {
    if (!notice || notice.sticky) return;
    const timer = window.setTimeout(() => notify(null), notice.tone === "error" ? 10_000 : 4_000);
    return () => window.clearTimeout(timer);
  }, [notice, notify]);
  if (!notice) return null;
  const error = notice.tone === "error";
  return (
    <div
      role={error ? "alert" : "status"}
      className={`fixed bottom-4 left-1/2 z-[80] flex max-w-xl -translate-x-1/2 items-start gap-2 rounded-md border px-3 py-2 text-sm shadow-lg ${
        error ? "border-danger/40 bg-danger/10 text-danger" : "border-control bg-surface"
      }`}
    >
      <span className="break-words">{notice.text}</span>
      <button
        type="button"
        aria-label="Dismiss"
        title="Dismiss"
        onClick={() => notify(null)}
        className="rounded p-0.5 opacity-60 hover:opacity-100"
      >
        <Glyph name="x" className="size-3.5" />
      </button>
    </div>
  );
}
