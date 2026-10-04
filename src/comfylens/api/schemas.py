"""Request and response models for every endpoint. The frontend mirrors these types."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from comfylens.analytics.scope import Filters, Scope
from comfylens.analytics.timeline import Bucket
from comfylens.metadata.types import Status

SortKey = Literal["generated_at", "rel_path", "family", "steps", "cfg"]
Section = Literal["numeric", "categorical", "seeds", "loras", "stacks", "configs"]
ALL_SECTIONS: list[Section] = ["numeric", "categorical", "seeds", "loras", "stacks", "configs"]


# Filters, LoraFilter and Scope live in analytics.scope, where they are read.


class ScopeInfo(BaseModel):
    scope_kind: Literal["selection", "filtered", "all"]
    scope_size: int  # files in scope
    excluded_no_metadata: int  # files in scope without a generations row
    duplicates_removed: int  # identical files counted once (dedupe_identical_files)
    analyzed: int  # files the statistics cover


# Library, index, facets.


class IndexStatusModel(BaseModel):
    state: Literal["idle", "scanning", "processing", "finalizing"]
    total: int
    done: int
    errors: int
    started_at: float | None
    last_error: str | None = None  # message of the last failed run, e.g. another indexer
    last_finished_at: float | None = None


class Versions(BaseModel):
    app: str
    schema_version: int
    extractor_version: int


class LibraryInfo(BaseModel):
    root: str
    total: int
    counts_by_status: dict[str, int]
    counts_by_family: dict[str, int]
    timestamp_suspect: int
    fts_available: bool
    last_index_at: int | None
    index: IndexStatusModel
    versions: Versions
    snapshot_built_at: float | None
    prompts_ready: bool
    watching: bool  # serve --watch: new and changed files are indexed automatically


class FacetValue(BaseModel):
    value: str
    count: int


class Range(BaseModel):
    min: float | None
    max: float | None


class DateRange(BaseModel):
    min: date | None
    max: date | None


class Facets(BaseModel):
    families: list[FacetValue]
    base_models: list[FacetValue]
    samplers: list[FacetValue]
    schedulers: list[FacetValue]
    loras: list[FacetValue]
    statuses: list[FacetValue]
    date_range: DateRange
    numeric_ranges: dict[str, Range]  # steps, cfg, denoise, guidance, shift


# Images.


class Sort(BaseModel):
    key: SortKey = "generated_at"
    descending: bool = True


class ImagesQuery(BaseModel):
    filters: Filters = Filters()
    sort: Sort = Sort()
    offset: int = Field(0, ge=0)
    limit: int = Field(500, ge=1, le=2000)


class ImageItem(BaseModel):
    id: int
    content_hash: str
    rel_path: str
    width: int | None
    height: int | None
    family: str | None
    generated_at: int | None
    status: Status
    has_warnings: bool
    timestamp_suspect: bool


class ImagesPage(BaseModel):
    total: int
    offset: int
    items: list[ImageItem]


class IdsQuery(BaseModel):
    filters: Filters = Filters()
    sort: Sort = Sort()


class IdsResponse(BaseModel):
    ids: list[int]


# Renaming and trashing files.

TRASH_BATCH = 500  # ids per trash request; the frontend splits larger selections


class RenameRequest(BaseModel):
    name: str  # the new base name, extension included; the directory stays


class RenameResponse(BaseModel):
    id: int
    rel_path: str
    generated_at: int


class TrashRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=TRASH_BATCH)


class TrashFailure(BaseModel):
    id: int
    message: str


class TrashResponse(BaseModel):
    trashed: list[int]  # moved to the system trash, or already gone; no longer in the catalog
    failed: list[TrashFailure]


class DetailFile(BaseModel):
    id: int
    rel_path: str
    format: str
    size: int
    width: int | None
    height: int | None
    megapixels: float | None
    aspect: float | None
    aspect_label: str | None
    content_hash: str
    generated_at: int | None
    timestamp_suspect: bool
    status: Status
    error: str | None


class DetailGeneration(BaseModel):
    model_family: str
    base_model: str | None
    text_encoder: str | None
    clip_type: str | None
    vae: str | None
    seed: str | None
    steps: int | None
    cfg: float | None
    sampler_name: str | None
    scheduler: str | None
    denoise: float | None
    guidance: float | None
    shift: float | None
    stage_count: int
    latent_source: str | None
    batch_size: int | None
    positive_prompt: str | None
    negative_prompt: str | None
    lora_stack_key: str
    config_key: str | None
    generation_key: str | None


class DetailStage(BaseModel):
    index: int
    node_id: str
    class_type: str
    seed: str | None
    steps: int | None
    cfg: float | None
    sampler_name: str | None
    scheduler: str | None
    denoise: float | None
    start_step: int | None
    end_step: int | None
    model_family: str
    base_model: str | None
    text_encoder: str | None
    clip_type: str | None
    lora_stack_key: str
    positive_prompt: str | None
    negative_prompt: str | None
    guidance: float | None
    shift: float | None
    latent_source: str | None


class DetailLora(BaseModel):
    position: int | None  # in its stage's chain
    stage_index: int | None  # None when on no stage's chain
    node_id: str
    entry: str
    class_type: str
    name_raw: str
    name: str
    base_name: str
    step: int | None
    strength_model: float | None
    strength_clip: float | None
    enabled: bool
    reachable: bool


class DetailInputImage(BaseModel):
    node_id: str
    filename: str | None
    sha256: str | None


class DetailNode(BaseModel):
    id: str
    class_type: str
    title: str | None
    reachable: bool
    inputs: dict[str, Any]  # literals as-is; links as [source id, slot]


class DetailWarning(BaseModel):
    code: str
    node_id: str | None
    message: str | None


class ImageDetail(BaseModel):
    file: DetailFile
    generation: DetailGeneration | None
    stages: list[DetailStage]
    loras: list[DetailLora]
    input_images: list[DetailInputImage]
    nodes: list[DetailNode]
    warnings: list[DetailWarning]


class RawResponse(BaseModel):
    sources: dict[str, str]
    prompt: Any | None  # parsed API prompt
    workflow: Any | None  # parsed UI workflow
    other: dict[str, Any]  # other text keys: parsed JSON where possible, else text


# Statistics.


class HistogramBar(BaseModel):
    x0: float  # discrete histograms: x0 == x1 == the value
    x1: float
    count: int


class Histogram(BaseModel):
    kind: Literal["discrete", "bins"]
    bars: list[HistogramBar]


class NumericStats(BaseModel):
    n: int
    n_missing: int
    mode: list[float]  # up to 3 ascending when tied; [] when no value repeats
    mode_tied: bool
    mode_note: str | None
    mode_share: float | None
    median: float | None
    mean: float | None
    std: float | None
    min: float | None
    p25: float | None
    p75: float | None
    max: float | None
    histogram: Histogram | None


class CategoryValue(BaseModel):
    value: str
    count: int
    share: float


class Categorical(BaseModel):
    n: int  # files with a value
    values: list[CategoryValue]  # top_n by count
    other: int  # files with a value outside the top_n
    missing: int  # files without a value


class RepeatedSeed(BaseModel):
    seed: str
    count: int


class SeedStats(BaseModel):
    n: int
    n_unique: int
    repeated: list[RepeatedSeed]  # up to 10 seeds used two or more times


class IntCount(BaseModel):
    value: int | None
    count: int


class LoraRow(BaseModel):
    name: str  # LoRA name or base name, by lora_key
    images: int
    share: float
    strength_model: NumericStats  # over files that use the LoRA only
    strength_clip: NumericStats | None
    positions: list[IntCount]
    steps: list[IntCount] | None  # base_name grouping only


class StackRow(BaseModel):
    key: str
    count: int
    share: float
    examples: list[int]  # up to 6 file ids, most recent first
    example_hashes: list[str]  # their content hashes, for /thumbs


class ConfigRow(BaseModel):
    key: str
    count: int
    share: float
    fields: dict[str, Any]  # model_family, base_model, lora_stack_key, sampler_name, ...
    examples: list[int]
    example_hashes: list[str]


class FamilyStats(BaseModel):
    family: str  # or "all" when pooled
    images: int
    numeric: dict[str, NumericStats] | None = None
    categorical: dict[str, Categorical] | None = None
    seeds: SeedStats | None = None
    loras: list[LoraRow] | None = None
    stacks: list[StackRow] | None = None
    configs: list[ConfigRow] | None = None


class StatsRequest(Scope):
    sections: list[Section] = ALL_SECTIONS
    lora_key: Literal["name", "base_name"] = "name"


class StatsResponse(BaseModel):
    scope: ScopeInfo
    groups: list[FamilyStats]  # largest first


# Timeline.


class TimelineRequest(Scope):
    bucket: Bucket = "day"


class TimelineResponse(BaseModel):
    bucket: Bucket
    buckets: list[date]  # first day of each bucket, ascending, contiguous
    series: dict[str, list[int]]  # family -> counts aligned with buckets
    suspect: list[int]
    selected: list[int] | None  # when the scope has a selection
    date_min: date | None  # of the filtered set without its date filter
    date_max: date | None


# Prompts.


class PromptsRequest(Scope):
    side: Literal["positive", "negative"] = "positive"
    include_template: bool = False
    by: Literal["image", "unique_prompt"] = "image"


class TermRow(BaseModel):
    term: str
    df: int
    share: float


class TemplateSentence(BaseModel):
    text: str
    df: int
    share: float


class DistinctPrompt(BaseModel):
    key: str
    text: str
    count: int
    share: float
    first: int | None  # generated_at
    last: int | None
    examples: list[int]
    example_hashes: list[str]


class PromptGroup(BaseModel):
    family: str
    images: int  # in scope, with a non-empty prompt on this side
    distinct_total: int
    all_template: bool  # every sentence in scope is template text
    templates: list[TemplateSentence]
    phrases: list[TermRow]
    unigrams: list[TermRow]
    bigrams: list[TermRow]
    trigrams: list[TermRow]
    distinct: list[DistinctPrompt]  # top 50 by count


class PromptsResponse(BaseModel):
    scope: ScopeInfo
    side: Literal["positive", "negative"]
    groups: list[PromptGroup]


# Distinctive terms.


class DistinctiveRequest(Scope):
    """The selection is compared with the rest of the filtered set (filters without dates are
    applied as usual). A non-empty selection is required."""

    side: Literal["positive", "negative"] = "positive"
    by: Literal["image", "unique_prompt"] = "image"


class DistinctiveTerm(BaseModel):
    term: str
    z: float  # z-scored log-odds ratio, informative Dirichlet prior; |z| >= 1.96 is notable
    selection_df: int
    selection_share: float
    rest_df: int
    rest_share: float


class DistinctiveList(BaseModel):
    selection: list[DistinctiveTerm]  # characteristic of the selection: highest z first
    rest: list[DistinctiveTerm]  # characteristic of the rest: lowest z first


class DistinctiveGroup(BaseModel):
    family: str
    selection_images: int  # with a non-empty prompt on this side
    rest_images: int
    phrases: DistinctiveList
    unigrams: DistinctiveList
    bigrams: DistinctiveList
    trigrams: DistinctiveList


class DistinctiveResponse(BaseModel):
    scope: ScopeInfo  # of the selection
    side: Literal["positive", "negative"]
    groups: list[DistinctiveGroup]  # families present in the selection, largest first


# Generic node inputs.


class NodeInputKey(BaseModel):
    class_type: str
    input_name: str
    kind: Literal["num", "str", "bool", "json"]
    files: int


class NodeKeysResponse(BaseModel):
    scope: ScopeInfo
    keys: list[NodeInputKey]  # most files first


class NodeStatsRequest(Scope):
    class_type: str
    input_name: str


class NodeStatsGroup(BaseModel):
    family: str
    files: int
    kind: Literal["num", "str", "bool", "json"]
    numeric: NumericStats | None = None
    categorical: Categorical | None = None
    n_unique: int | None = None  # strings longer than 200 characters report only this


class NodeStatsResponse(BaseModel):
    scope: ScopeInfo
    class_type: str
    input_name: str
    groups: list[NodeStatsGroup]
