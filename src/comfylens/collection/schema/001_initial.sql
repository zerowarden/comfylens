-- Collection schema, migration 1. Migrations are never edited once released: add a new file.

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- keys: revision (incremented by every write transaction)

-- Reference images, copied byte for byte.
CREATE TABLE originals (
  content_hash TEXT PRIMARY KEY,          -- xxh3_128 hex, as in the catalog
  format TEXT NOT NULL CHECK (format IN ('png', 'jpeg', 'webp')),
  width INTEGER NOT NULL, height INTEGER NOT NULL, size INTEGER NOT NULL,
  api_prompt TEXT, workflow TEXT,         -- JSON text as found in the file, or NULL
  added_at INTEGER NOT NULL
);

CREATE TABLE prompts (
  id INTEGER PRIMARY KEY,
  uid TEXT NOT NULL UNIQUE,               -- uuid4 hex; identity across export and import
  title TEXT NOT NULL,
  positive TEXT NOT NULL, negative TEXT NOT NULL,
  positive_key TEXT,                      -- prompt_key(positive) as 16 hex digits; NULL if empty
  notes TEXT NOT NULL, source_url TEXT, model_family TEXT,
  settings TEXT NOT NULL,                 -- PromptSettings JSON
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE INDEX prompts_key ON prompts(positive_key);

-- A reference has a row in originals; an attempt is a library image, linked by content hash.
CREATE TABLE prompt_images (
  prompt_id INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
  content_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('reference', 'attempt')),
  position INTEGER NOT NULL,              -- order within its role
  added_at INTEGER NOT NULL,
  PRIMARY KEY (prompt_id, content_hash)
);
CREATE INDEX prompt_images_hash ON prompt_images(content_hash);

CREATE TABLE prompt_tags (
  prompt_id INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  PRIMARY KEY (prompt_id, tag)
);
