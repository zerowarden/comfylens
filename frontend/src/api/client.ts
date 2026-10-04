import type {
  DistinctiveRequest,
  DistinctiveResponse,
  Facets,
  IdsQuery,
  IdsResponse,
  ImageDetail,
  ImagesPage,
  ImagesQuery,
  IndexStatusModel,
  LibraryInfo,
  NodeKeysResponse,
  NodeStatsRequest,
  NodeStatsResponse,
  PromptsRequest,
  PromptsResponse,
  RawResponse,
  RenameRequest,
  RenameResponse,
  Scope,
  StatsRequest,
  StatsResponse,
  TimelineRequest,
  TimelineResponse,
  TrashRequest,
  TrashResponse,
} from "./types";

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
  const response = await fetch(path, init);
  if (response.ok) return (await response.json()) as T;

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // Not JSON: keep the status text.
  }
  if (payload && typeof payload === "object") {
    const p = payload as { warming?: boolean; error?: { code?: string; message?: string } };
    if (p.warming)
      throw new ApiError(response.status, "warming", "Prompt analysis is warming up", true);
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
  stats: (q: StatsRequest) => request<StatsResponse>("/api/stats", q),
  timeline: (q: TimelineRequest) => request<TimelineResponse>("/api/timeline", q),
  prompts: (q: PromptsRequest) => request<PromptsResponse>("/api/prompts", q),
  distinctive: (q: DistinctiveRequest) =>
    request<DistinctiveResponse>("/api/prompts/distinctive", q),
  nodeKeys: (q: Scope) => request<NodeKeysResponse>("/api/node-inputs/keys", q),
  nodeStats: (q: NodeStatsRequest) => request<NodeStatsResponse>("/api/node-inputs/stats", q),
};

export const thumbUrl = (contentHash: string) => `/thumbs/${contentHash}.webp`;
export const fileUrl = (id: number) => `/api/images/${id}/file`;
