import type {
  CollectionList,
  DeleteResponse,
  DistinctiveRequest,
  DistinctiveResponse,
  Draft,
  Facets,
  IdsQuery,
  IdsResponse,
  ImageCollection,
  ImageDetail,
  ImportResponse,
  ImagesPage,
  ImagesQuery,
  IndexStatusModel,
  LibraryInfo,
  LinkRequest,
  LinkResponse,
  NodeKeysResponse,
  NodeStatsRequest,
  NodeStatsResponse,
  PromptInput,
  PromptsRequest,
  PromptsResponse,
  RawOriginal,
  RawResponse,
  RenameRequest,
  RenameResponse,
  SavedPrompt,
  Scope,
  StatsRequest,
  StatsResponse,
  TextDraftRequest,
  TimelineRequest,
  TimelineResponse,
  TrashRequest,
  TrashResponse,
  UnlinkRequest,
} from "./types";
import { attachmentName } from "../lib/files";

/** Shown wherever a prompt-analysis query is still warming up. */
export const WARMING_TEXT = "Prompt analysis is warming up…";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /** /api/prompts answers 503 {"warming": true} until prompt frames are built. */
  readonly warming: boolean;

  constructor(status: number, code: string, message: string, warming = false) {
    super(message);
    this.status = status;
    this.code = code;
    this.warming = warming;
  }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const init: RequestInit =
    body === undefined
      ? { method: "GET" }
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        };
  return parse<T>(await fetch(path, init));
}

/** POST a file as the raw request body. */
async function upload<T>(path: string, file: Blob): Promise<T> {
  return parse<T>(
    await fetch(path, {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    }),
  );
}

/** A file the server sends as an attachment, with the name it gives it. */
async function download(path: string): Promise<{ blob: Blob; name: string | null }> {
  const response = await fetch(path);
  if (!response.ok) return parse<never>(response);
  const name = attachmentName(response.headers.get("Content-Disposition") ?? "");
  return { blob: await response.blob(), name };
}

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // Not JSON: keep the status text.
  }
  if (payload && typeof payload === "object") {
    const p = payload as { warming?: boolean; error?: { code?: string; message?: string } };
    if (p.warming) throw new ApiError(response.status, "warming", WARMING_TEXT, true);
    if (p.error) {
      throw new ApiError(response.status, p.error.code ?? "error", p.error.message ?? "");
    }
  }
  throw new ApiError(response.status, "http", `${response.status} ${response.statusText}`);
}

export const api = {
  library: () => request<LibraryInfo>("/api/library"),
  indexStatus: () => request<IndexStatusModel>("/api/index/status"),
  rescan: () => request<IndexStatusModel>("/api/index/rescan", {}),
  facets: () => request<Facets>("/api/facets"),
  images: (q: ImagesQuery) => request<ImagesPage>("/api/images/query", q),
  ids: (q: IdsQuery) => request<IdsResponse>("/api/images/ids", q),
  image: (id: number) => request<ImageDetail>(`/api/images/${id}`),
  raw: (id: number) => request<RawResponse>(`/api/images/${id}/raw`),
  rename: (id: number, name: string) =>
    request<RenameResponse>(`/api/images/${id}/rename`, { name } satisfies RenameRequest),
  trash: (ids: number[]) =>
    request<TrashResponse>("/api/images/trash", { ids } satisfies TrashRequest),
  stripped: (id: number) => download(`/api/images/${id}/stripped`),
  stats: (q: StatsRequest) => request<StatsResponse>("/api/stats", q),
  timeline: (q: TimelineRequest) => request<TimelineResponse>("/api/timeline", q),
  prompts: (q: PromptsRequest) => request<PromptsResponse>("/api/prompts", q),
  distinctive: (q: DistinctiveRequest) =>
    request<DistinctiveResponse>("/api/prompts/distinctive", q),
  nodeKeys: (q: Scope) => request<NodeKeysResponse>("/api/node-inputs/keys", q),
  nodeStats: (q: NodeStatsRequest) => request<NodeStatsResponse>("/api/node-inputs/stats", q),
  collection: (q: { q?: string; tag?: string | null; family?: string | null }) => {
    const p = new URLSearchParams();
    if (q.q?.trim()) p.set("q", q.q.trim());
    if (q.tag) p.set("tag", q.tag);
    if (q.family) p.set("family", q.family);
    const search = p.toString();
    return request<CollectionList>(`/api/collection/prompts${search ? `?${search}` : ""}`);
  },
  savedPrompt: (id: number) => request<SavedPrompt>(`/api/collection/prompts/${id}`),
  createPrompt: (body: PromptInput) => request<SavedPrompt>("/api/collection/prompts", body),
  updatePrompt: (id: number, body: PromptInput) =>
    request<SavedPrompt>(`/api/collection/prompts/${id}`, body),
  deletePrompt: (id: number) => request<DeleteResponse>(`/api/collection/prompts/${id}/delete`, {}),
  linkAttempts: (id: number, fileIds: number[]) =>
    request<LinkResponse>(`/api/collection/prompts/${id}/attempts`, {
      file_ids: fileIds,
    } satisfies LinkRequest),
  unlinkAttempts: (id: number, hashes: string[]) =>
    request<SavedPrompt>(`/api/collection/prompts/${id}/attempts/remove`, {
      hashes,
    } satisfies UnlinkRequest),
  draftFromFile: (file: Blob) => upload<Draft>("/api/collection/drafts/upload", file),
  draftFromImage: (id: number) => request<Draft>(`/api/collection/drafts/from-image/${id}`, {}),
  draftFromText: (body: TextDraftRequest) => request<Draft>("/api/collection/drafts/text", body),
  imageCollection: (id: number) => request<ImageCollection>(`/api/collection/for-image/${id}`),
  originalRaw: (hash: string) => request<RawOriginal>(`/api/collection/originals/${hash}/raw`),
  importCollection: (archive: Blob) => upload<ImportResponse>("/api/collection/import", archive),
};

export const thumbUrl = (contentHash: string) => `/thumbs/${contentHash}.webp`;
export const fileUrl = (id: number) => `/api/images/${id}/file`;
export const originalUrl = (hash: string) => `/api/collection/originals/${hash}`;
export const EXPORT_URL = "/api/collection/export";
