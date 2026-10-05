// Mirrors src/comfylens/api/schemas.py field for field. Keep the two in sync.

export type Status = "ok" | "partial" | "no_metadata" | "error";
export type SortKey = "generated_at" | "rel_path" | "family" | "steps" | "cfg";
export type NumericFilterField = "steps" | "cfg" | "denoise" | "guidance" | "shift";
export type Bucket = "day" | "week" | "month";
export type Section = "numeric" | "categorical" | "seeds" | "loras" | "stacks" | "configs";
export type GenericKind = "num" | "str" | "bool" | "json";
export type ImageRole = "reference" | "attempt";
export type DraftMetadata = "comfyui" | "a1111" | "none";

export interface LoraFilter {
  names: string[];
  mode: "any" | "all";
}

export interface Filters {
  families: string[];
  base_models: string[];
  samplers: string[];
  schedulers: string[];
  loras: LoraFilter;
  date_from: string | null; // YYYY-MM-DD, inclusive
  date_to: string | null;
  statuses: Status[];
  text: string;
  numeric: Partial<Record<NumericFilterField, [number, number]>>;
  has_warnings: boolean | null;
  saved: boolean | null; // linked to any saved prompt (or to none)
  saved_prompt: number | null; // one saved prompt's files: linked, or the same prompt
}

export interface Scope {
  selection: number[];
  filters: Filters;
}

export interface ScopeInfo {
  scope_kind: "selection" | "filtered" | "all";
  scope_size: number;
  excluded_no_metadata: number;
  duplicates_removed: number;
  analyzed: number;
}

export interface IndexStatusModel {
  state: "idle" | "scanning" | "processing" | "finalizing";
  total: number;
  done: number;
  errors: number;
  started_at: number | null;
  last_error: string | null;
  last_finished_at: number | null;
}

export interface Versions {
  app: string;
  schema_version: number;
  extractor_version: number;
}

export interface LibraryInfo {
  root: string;
  total: number;
  counts_by_status: Record<string, number>;
  counts_by_family: Record<string, number>;
  timestamp_suspect: number;
  fts_available: boolean;
  last_index_at: number | null;
  index: IndexStatusModel;
  versions: Versions;
  snapshot_built_at: number | null;
  prompts_ready: boolean;
  /** serve --watch: new and changed files are indexed automatically. */
  watching: boolean;
}

export interface FacetValue {
  value: string;
  count: number;
}

export interface Range {
  min: number | null;
  max: number | null;
}

export interface DateRange {
  min: string | null;
  max: string | null;
}

export interface Facets {
  families: FacetValue[];
  base_models: FacetValue[];
  samplers: FacetValue[];
  schedulers: FacetValue[];
  loras: FacetValue[];
  statuses: FacetValue[];
  date_range: DateRange;
  numeric_ranges: Record<string, Range>;
}

export interface Sort {
  key: SortKey;
  descending: boolean;
}

export interface ImagesQuery {
  filters: Filters;
  sort: Sort;
  offset: number;
  limit: number;
}

export interface ImageItem {
  id: number;
  content_hash: string;
  rel_path: string;
  width: number | null;
  height: number | null;
  family: string | null;
  generated_at: number | null;
  status: Status;
  has_warnings: boolean;
  timestamp_suspect: boolean;
  saved: boolean; // linked to a saved prompt in the collection
}

export interface ImagesPage {
  total: number;
  offset: number;
  items: ImageItem[];
}

export interface IdsQuery {
  filters: Filters;
  sort: Sort;
}

export interface IdsResponse {
  ids: number[];
}

export interface RenameRequest {
  name: string; // the new base name, extension included; the directory stays
}

export interface RenameResponse {
  id: number;
  rel_path: string;
  generated_at: number;
}

export interface TrashRequest {
  ids: number[]; // 1 to TRASH_BATCH
}

export interface TrashFailure {
  id: number;
  message: string;
}

export interface TrashResponse {
  trashed: number[]; // moved to the system trash, or already gone; no longer in the catalog
  failed: TrashFailure[];
}

export interface DetailFile {
  id: number;
  rel_path: string;
  format: string;
  size: number;
  width: number | null;
  height: number | null;
  megapixels: number | null;
  aspect: number | null;
  aspect_label: string | null;
  content_hash: string;
  generated_at: number | null;
  timestamp_suspect: boolean;
  status: Status;
  error: string | null;
}

export interface DetailGeneration {
  model_family: string;
  base_model: string | null;
  text_encoder: string | null;
  clip_type: string | null;
  vae: string | null;
  seed: string | null;
  steps: number | null;
  cfg: number | null;
  sampler_name: string | null;
  scheduler: string | null;
  denoise: number | null;
  guidance: number | null;
  shift: number | null;
  stage_count: number;
  latent_source: string | null;
  batch_size: number | null;
  positive_prompt: string | null;
  negative_prompt: string | null;
  lora_stack_key: string;
  config_key: string | null;
  generation_key: string | null;
}

export interface DetailStage {
  index: number;
  node_id: string;
  class_type: string;
  seed: string | null;
  steps: number | null;
  cfg: number | null;
  sampler_name: string | null;
  scheduler: string | null;
  denoise: number | null;
  start_step: number | null;
  end_step: number | null;
  model_family: string;
  base_model: string | null;
  text_encoder: string | null;
  clip_type: string | null;
  lora_stack_key: string;
  positive_prompt: string | null;
  negative_prompt: string | null;
  guidance: number | null;
  shift: number | null;
  latent_source: string | null;
}

export interface DetailLora {
  /** In its stage's chain; null when switched off or unused. */
  position: number | null;
  /** The stage whose model chain holds it; null when on none. */
  stage_index: number | null;
  node_id: string;
  entry: string;
  class_type: string;
  name_raw: string;
  name: string;
  base_name: string;
  step: number | null;
  strength_model: number | null;
  strength_clip: number | null;
  enabled: boolean;
  reachable: boolean;
}

export interface DetailInputImage {
  node_id: string;
  filename: string | null;
  sha256: string | null;
}

export interface DetailNode {
  id: string;
  class_type: string;
  title: string | null;
  reachable: boolean;
  inputs: Record<string, unknown>;
}

export interface DetailWarning {
  code: string;
  node_id: string | null;
  message: string | null;
}

export interface ImageDetail {
  file: DetailFile;
  generation: DetailGeneration | null;
  stages: DetailStage[];
  loras: DetailLora[];
  input_images: DetailInputImage[];
  nodes: DetailNode[];
  warnings: DetailWarning[];
}

export interface RawResponse {
  sources: Record<string, string>;
  prompt: unknown;
  workflow: unknown;
  other: Record<string, unknown>;
}

export interface HistogramBar {
  x0: number;
  x1: number;
  count: number;
}

export interface Histogram {
  kind: "discrete" | "bins";
  bars: HistogramBar[];
}

export interface NumericStats {
  n: number;
  n_missing: number;
  mode: number[];
  mode_tied: boolean;
  mode_note: string | null;
  mode_share: number | null;
  median: number | null;
  mean: number | null;
  std: number | null;
  min: number | null;
  p25: number | null;
  p75: number | null;
  max: number | null;
  histogram: Histogram | null;
}

export interface CategoryValue {
  value: string;
  count: number;
  share: number;
}

export interface Categorical {
  n: number;
  values: CategoryValue[];
  other: number;
  missing: number;
}

export interface RepeatedSeed {
  seed: string;
  count: number;
}

export interface SeedStats {
  n: number;
  n_unique: number;
  repeated: RepeatedSeed[];
}

export interface IntCount {
  value: number | null;
  count: number;
}

export interface LoraRow {
  name: string;
  images: number;
  share: number;
  strength_model: NumericStats;
  strength_clip: NumericStats | null;
  positions: IntCount[];
  steps: IntCount[] | null;
}

export interface StackRow {
  key: string;
  count: number;
  share: number;
  examples: number[];
  example_hashes: string[];
}

export interface ConfigRow {
  key: string;
  count: number;
  share: number;
  fields: Record<string, unknown>;
  examples: number[];
  example_hashes: string[];
}

export interface FamilyStats {
  family: string;
  images: number;
  numeric: Record<string, NumericStats> | null;
  categorical: Record<string, Categorical> | null;
  seeds: SeedStats | null;
  loras: LoraRow[] | null;
  stacks: StackRow[] | null;
  configs: ConfigRow[] | null;
}

export interface StatsRequest extends Scope {
  sections: Section[];
  lora_key: "name" | "base_name";
}

export interface StatsResponse {
  scope: ScopeInfo;
  groups: FamilyStats[];
}

export interface TimelineRequest extends Scope {
  bucket: Bucket;
}

export interface TimelineResponse {
  bucket: Bucket;
  buckets: string[];
  series: Record<string, number[]>;
  suspect: number[];
  selected: number[] | null;
  date_min: string | null;
  date_max: string | null;
}

export type PromptSide = "positive" | "negative";

export interface PromptsRequest extends Scope {
  side: PromptSide;
  include_template: boolean;
  by: "image" | "unique_prompt";
}

export interface TermRow {
  term: string;
  df: number;
  share: number;
}

export interface TemplateSentence {
  text: string;
  df: number;
  share: number;
}

export interface DistinctPrompt {
  key: string;
  text: string;
  count: number;
  share: number;
  first: number | null;
  last: number | null;
  examples: number[];
  example_hashes: string[];
}

export interface PromptGroup {
  family: string;
  images: number;
  distinct_total: number;
  all_template: boolean;
  templates: TemplateSentence[];
  phrases: TermRow[];
  unigrams: TermRow[];
  bigrams: TermRow[];
  trigrams: TermRow[];
  distinct: DistinctPrompt[];
}

export interface PromptsResponse {
  scope: ScopeInfo;
  side: PromptSide;
  groups: PromptGroup[];
}

/** The selection (required) is compared with the rest of the filtered set. */
export interface DistinctiveRequest extends Scope {
  side: PromptSide;
  by: "image" | "unique_prompt";
}

export interface DistinctiveTerm {
  term: string;
  /** z-scored log-odds ratio with an informative Dirichlet prior; |z| >= 1.96 is notable. */
  z: number;
  selection_df: number;
  selection_share: number;
  rest_df: number;
  rest_share: number;
}

export interface DistinctiveList {
  /** Characteristic of the selection: highest z first. */
  selection: DistinctiveTerm[];
  /** Characteristic of the rest: lowest z first. */
  rest: DistinctiveTerm[];
}

export interface DistinctiveGroup {
  family: string;
  selection_images: number;
  rest_images: number;
  phrases: DistinctiveList;
  unigrams: DistinctiveList;
  bigrams: DistinctiveList;
  trigrams: DistinctiveList;
}

export interface DistinctiveResponse {
  scope: ScopeInfo;
  side: PromptSide;
  groups: DistinctiveGroup[];
}

export interface NodeInputKey {
  class_type: string;
  input_name: string;
  kind: GenericKind;
  files: number;
}

export interface NodeKeysResponse {
  scope: ScopeInfo;
  keys: NodeInputKey[];
}

export interface NodeStatsRequest extends Scope {
  class_type: string;
  input_name: string;
}

export interface NodeStatsGroup {
  family: string;
  files: number;
  kind: GenericKind;
  numeric: NumericStats | null;
  categorical: Categorical | null;
  n_unique: number | null;
}

export interface NodeStatsResponse {
  scope: ScopeInfo;
  class_type: string;
  input_name: string;
  groups: NodeStatsGroup[];
}

export interface SavedLora {
  name: string;
  strength_model: number | null;
  strength_clip: number | null;
}

export interface PromptSettings {
  base_model: string | null;
  seed: string | null;
  steps: number | null;
  cfg: number | null;
  sampler_name: string | null;
  scheduler: string | null;
  denoise: number | null;
  guidance: number | null;
  shift: number | null;
  loras: SavedLora[];
}

export interface PromptInput {
  title: string;
  positive: string;
  negative: string;
  notes: string;
  source_url: string | null;
  model_family: string | null;
  tags: string[];
  settings: PromptSettings;
  references: string[]; // content hashes of collection images, in order
  attempts: string[]; // content hashes linked in addition to existing attempts
}

export interface CollectionImage {
  content_hash: string;
  role: ImageRole;
  format: string | null; // null when the collection holds no copy
  width: number | null;
  height: number | null;
  has_workflow: boolean;
  library_ids: number[]; // files with this content hash in the served library
}

export interface PromptSummary {
  id: number;
  title: string;
  positive: string;
  model_family: string | null;
  tags: string[];
  cover_hash: string | null;
  reference_count: number;
  attempt_count: number;
  library_count: number | null; // null while prompt analysis warms up
  updated_at: number;
}

export interface CollectionList {
  items: PromptSummary[];
  tags: FacetValue[];
  families: FacetValue[];
}

export interface SavedPrompt {
  id: number;
  uid: string;
  title: string;
  positive: string;
  negative: string;
  notes: string;
  source_url: string | null;
  model_family: string | null;
  tags: string[];
  settings: PromptSettings;
  references: CollectionImage[];
  attempts: CollectionImage[];
  library_count: number | null;
  created_at: number;
  updated_at: number;
}

export interface Draft {
  original: CollectionImage | null;
  title: string;
  positive: string;
  negative: string;
  model_family: string | null;
  settings: PromptSettings;
  metadata: DraftMetadata;
}

export interface TextDraftRequest {
  positive: string;
  negative: string;
}

export interface LinkRequest {
  file_ids: number[];
}

export interface LinkResponse {
  added: number;
  skipped: number[];
}

export interface UnlinkRequest {
  hashes: string[];
}

export interface DeleteResponse {
  deleted: boolean;
}

export interface PromptRef {
  id: number;
  title: string;
  role: ImageRole | null;
}

export interface ImageCollection {
  linked: PromptRef[];
  matching: PromptRef[];
}

export interface ImportResponse {
  added: number; // prompts new to this collection
  skipped: number; // prompts it already had
  images: number; // reference images in the archive
}

export interface RawOriginal {
  prompt: unknown;
  workflow: unknown;
}
