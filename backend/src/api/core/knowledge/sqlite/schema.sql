-- Core activity storage
CREATE TABLE IF NOT EXISTS activities (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    app_name TEXT NOT NULL,
    window_title TEXT,
    extracted_text TEXT,
    ai_analysis TEXT,
    duration INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    context_hash TEXT  -- For grouping similar contexts
);

-- Transcription storage
CREATE TABLE IF NOT EXISTS transcriptions (
    id TEXT PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    transcription_text TEXT NOT NULL,
    model_name TEXT NOT NULL,
    audio_file_path TEXT NOT NULL,
    duration_seconds REAL,
    language TEXT DEFAULT 'en',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Context information (all optional)
    app_name TEXT,
    window_title TEXT,
    task_category TEXT,
    
    -- User interaction (all optional)
    was_edited BOOLEAN DEFAULT FALSE,
    edit_distance INTEGER,
    edited_text TEXT,
    
    -- Performance metrics (all optional)
    confidence_score REAL,
    processing_time_ms INTEGER,
    user_rating INTEGER CHECK (user_rating BETWEEN 1 AND 5),
    user_feedback TEXT,
    
    -- Relationships (all optional)
    session_id TEXT,
    related_activity_id TEXT,
    
    -- Follow-up actions (optional)
    action_taken TEXT,

    -- Lifecycle state (added in 0.9.0)
    -- status is one of: 'pending', 'completed', 'failed'.
    -- Default 'completed' keeps pre-0.9.0 rows semantically identical.
    status TEXT NOT NULL DEFAULT 'completed',
    error_message TEXT
);

-- Suggestions storage
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id TEXT NOT NULL,
    context_text TEXT,
    suggestion_text TEXT NOT NULL,
    explanation_text TEXT,
    model_name TEXT NOT NULL,
    generated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_request TEXT,
    inserted_at TIMESTAMP,
    FOREIGN KEY (activity_id) REFERENCES activities(id)
);

-- Flexible attribute storage
CREATE TABLE IF NOT EXISTS activity_metadata (
    activity_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    FOREIGN KEY (activity_id) REFERENCES activities(id),
    PRIMARY KEY (activity_id, key)
);

-- Full-text search support
CREATE VIRTUAL TABLE IF NOT EXISTS activities_fts USING fts5(
    content,  -- Combined searchable text
    activity_id UNINDEXED,  -- Reference to main activities table
    timestamp UNINDEXED,
    tokenize='porter unicode61'
);

-- FTS synchronization triggers
CREATE TRIGGER IF NOT EXISTS activities_ai AFTER INSERT ON activities 
BEGIN
    INSERT INTO activities_fts(content, activity_id, timestamp)
    VALUES (
        new.window_title || ' ' || 
        COALESCE(new.extracted_text, '') || ' ' ||
        new.app_name,
        new.id,
        new.timestamp
    );
END;

CREATE TRIGGER IF NOT EXISTS activities_ad AFTER DELETE ON activities 
BEGIN
    DELETE FROM activities_fts WHERE activity_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS activities_au AFTER UPDATE ON activities 
BEGIN
    DELETE FROM activities_fts WHERE activity_id = old.id;
    INSERT INTO activities_fts(content, activity_id, timestamp)
    VALUES (
        new.window_title || ' ' || 
        COALESCE(new.extracted_text, '') || ' ' ||
        new.app_name,
        new.id,
        new.timestamp
    );
END;

-- Pattern storage for learning
CREATE TABLE IF NOT EXISTS activity_patterns (
    id TEXT PRIMARY KEY,
    pattern_type TEXT NOT NULL,
    pattern_data TEXT NOT NULL,  -- JSON
    occurrence_count INTEGER DEFAULT 1,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confidence REAL DEFAULT 1.0
);

-- Performance indices
CREATE INDEX IF NOT EXISTS idx_activities_timestamp ON activities(timestamp);
CREATE INDEX IF NOT EXISTS idx_activities_app_name ON activities(app_name);
CREATE INDEX IF NOT EXISTS idx_activities_context ON activities(context_hash);
CREATE INDEX IF NOT EXISTS idx_metadata_key_value ON activity_metadata(key, value);
CREATE INDEX IF NOT EXISTS idx_patterns_type ON activity_patterns(pattern_type);
CREATE INDEX IF NOT EXISTS idx_transcriptions_timestamp ON transcriptions(timestamp);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_info (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR REPLACE INTO schema_info (key, value) VALUES ('version', '0.3.1');