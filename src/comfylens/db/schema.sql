-- Catalog schema. Bump SCHEMA_VERSION in version.py with every change.

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- keys: schema_version, extractor_version, config_hash, library_root, last_index_at,
--       last_index_stats, timestamp_clusters

CREATE TABLE files (
  id INTEGER PRIMARY KEY,
  rel_path TEXT NOT NULL UNIQUE,          -- POSIX, relative to library root
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  content_hash TEXT NOT NULL,             -- xxh3_128 hex; '' if the file could not be read
  format TEXT NOT NULL,                   -- png | jpeg
  width INTEGER, height INTEGER,
  status TEXT NOT NULL,                   -- ok | partial | no_metadata | error
  error TEXT,
  generated_at INTEGER,                   -- unix seconds
  timestamp_suspect INTEGER NOT NULL DEFAULT 0,
  indexed_at INTEGER NOT NULL
);
CREATE INDEX files_hash ON files(content_hash);
CREATE INDEX files_generated ON files(generated_at);

CREATE TABLE raw_metadata (
  file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
  sources TEXT,                           -- JSON object: key -> source
  prompt_json TEXT,
  workflow_json TEXT,
  other_json TEXT                         -- JSON object of other text keys
);

CREATE TABLE generations (
  file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
  model_family TEXT NOT NULL,
  base_model TEXT, text_encoder TEXT, clip_type TEXT, vae TEXT,
  seed TEXT,                              -- up to 2^64-1; exceeds SQLite INTEGER
  steps INTEGER, cfg REAL, sampler_name TEXT, scheduler TEXT, denoise REAL,
  guidance REAL, shift REAL,
  stage_count INTEGER NOT NULL,
  latent_source TEXT, batch_size INTEGER,
  positive_prompt TEXT, negative_prompt TEXT,
  stage_prompts TEXT,                     -- later stages' differing prompts, for search only
  lora_stack_key TEXT NOT NULL,
  config_key TEXT,
  generation_key TEXT
);
CREATE INDEX gen_family ON generations(model_family);

CREATE TABLE sampler_stages (
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  stage_index INTEGER NOT NULL,
  node_id TEXT NOT NULL, class_type TEXT NOT NULL,
  seed TEXT, steps INTEGER, cfg REAL, sampler_name TEXT, scheduler TEXT,
  denoise REAL, start_step INTEGER, end_step INTEGER,
  -- what the stage ran with, traced from its own inputs
  model_family TEXT NOT NULL, base_model TEXT, text_encoder TEXT, clip_type TEXT,
  lora_stack_key TEXT NOT NULL,
  positive_prompt TEXT, negative_prompt TEXT,
  guidance REAL, shift REAL, latent_source TEXT,
  PRIMARY KEY (file_id, stage_index)
);

-- One row per stage whose model chain holds the LoRA; stage_index NULL when on none.
CREATE TABLE loras (
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  stage_index INTEGER,
  node_id TEXT NOT NULL,
  entry TEXT NOT NULL DEFAULT '',         -- '' or 'lora_N' (Power Lora Loader)
  position INTEGER,                       -- in the stage's chain; NULL when off or unused
  class_type TEXT NOT NULL,
  name_raw TEXT NOT NULL, name TEXT NOT NULL,
  base_name TEXT NOT NULL, step INTEGER,
  strength_model REAL, strength_clip REAL,
  enabled INTEGER NOT NULL, reachable INTEGER NOT NULL
);
CREATE UNIQUE INDEX loras_use ON loras(file_id, node_id, entry, stage_index);
CREATE INDEX loras_name ON loras(name);

CREATE TABLE input_images (
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  node_id TEXT NOT NULL, filename TEXT, sha256 TEXT,
  PRIMARY KEY (file_id, node_id)
);

-- Every node of the API prompt; node_inputs alone misses nodes with only linked inputs.
CREATE TABLE nodes (
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  node_id TEXT NOT NULL, class_type TEXT NOT NULL,
  reachable INTEGER NOT NULL,
  PRIMARY KEY (file_id, node_id)
);
CREATE INDEX nodes_class ON nodes(class_type);

CREATE TABLE node_inputs (
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  node_id TEXT NOT NULL, class_type TEXT NOT NULL,
  input_name TEXT NOT NULL,
  kind TEXT NOT NULL,                     -- num | str | bool | json
  value_num REAL,                         -- num, and bool as 0/1
  value_text TEXT,                        -- str and json
  reachable INTEGER NOT NULL
);
CREATE INDEX ni_key ON node_inputs(class_type, input_name);
CREATE INDEX ni_file ON node_inputs(file_id);

CREATE TABLE warnings (
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  code TEXT NOT NULL, node_id TEXT, message TEXT
);
CREATE INDEX warnings_code ON warnings(code);
CREATE INDEX warnings_file ON warnings(file_id);
