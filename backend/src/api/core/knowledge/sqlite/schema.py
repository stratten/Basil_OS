"""Core schema definitions for Basil knowledge base."""

from typing import List

from .sqlite_knowledge_service_component_services.schema_management.agent_work.schema import (
    get_agent_work_schema_statements,
)
from .sqlite_knowledge_service_component_services.schema_management.providers.discovery_schema import (
    get_provider_discovery_schema_statements,
)
from .sqlite_knowledge_service_component_services.schema_management.providers.run_schema import (
    get_provider_run_schema_statements,
)
from .zettel_schema import get_zettel_schema_statements

SCHEMA_VERSION = "0.17.0"  # durable provider target authorization attempts

def get_schema_statements() -> List[str]:
    """Get SQL statements for creating the database schema."""
    return [
        # Activities table - Core activity storage
        """
        CREATE TABLE IF NOT EXISTS activities (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            app_name TEXT NOT NULL,
            window_title TEXT,
            extracted_text TEXT,
            ai_analysis TEXT,
            duration INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            context_hash TEXT,  -- For grouping similar contexts
            capture_frequency_minutes REAL,  -- Frequency setting used for this capture
            observation_count INTEGER DEFAULT 1,  -- Number of compacted captures folded into this row
            last_observed_at TEXT,  -- Timestamp of the most recent compacted observation
            content_fingerprint TEXT  -- Native perceptual difference-hash of the captured screen
        )
        """,

        # Transcription storage
        """
        CREATE TABLE IF NOT EXISTS transcriptions (
            id TEXT PRIMARY KEY,
            timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            transcription_text TEXT NOT NULL,
            model_name TEXT NOT NULL,
            audio_file_path TEXT NOT NULL,
            duration_seconds REAL,
            language TEXT DEFAULT 'en',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_transcribed_at TIMESTAMP,
            
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
        )
        """,

        # Activity metadata - Flexible attribute storage
        """
        CREATE TABLE IF NOT EXISTS activity_metadata (
            activity_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            FOREIGN KEY (activity_id) REFERENCES activities(id),
            PRIMARY KEY (activity_id, key)
        )
        """,

        # Workflow todos - Generic todo workflow management for context isolation
        """
        CREATE TABLE IF NOT EXISTS workflow_todos (
            todo_id TEXT PRIMARY KEY,
            agent_task_id TEXT NOT NULL,
            title TEXT NOT NULL,                   -- Human-readable todo description
            initial_context TEXT NOT NULL,        -- JSON: starting context
            current_context TEXT NOT NULL,        -- JSON: accumulated step-based context  
            status TEXT NOT NULL DEFAULT 'pending', -- pending, in_progress, completed, failed
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            error_message TEXT,
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE
        )
        """,

        # Todo steps - Generic step execution history with data-agnostic storage
        """
        CREATE TABLE IF NOT EXISTS todo_steps (
            step_id TEXT PRIMARY KEY,
            todo_id TEXT NOT NULL,
            step_number INTEGER NOT NULL,
            context_at_step TEXT NOT NULL,        -- JSON: context available at this step
            operation TEXT NOT NULL,              -- e.g., "assistant_output_history_service.persist_assistant_output"
            parameters TEXT NOT NULL,             -- JSON: parameters passed to operation
            result TEXT,                          -- JSON: operation result (any data structure)
            status TEXT NOT NULL DEFAULT 'pending', -- pending, executing, completed, failed
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            error_message TEXT,
            FOREIGN KEY (todo_id) REFERENCES workflow_todos(todo_id) ON DELETE CASCADE
        )
        """,

        *get_agent_work_schema_statements(),

        *get_provider_run_schema_statements(),
        *get_provider_discovery_schema_statements(),

        *get_zettel_schema_statements(),

        # Full-text search table
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS activities_fts USING fts5(
            content,  -- Combined searchable text
            activity_id UNINDEXED,  -- Reference to main activities table
            timestamp UNINDEXED,
            tokenize='porter unicode61'
        )
        """,

        # FTS synchronization triggers
        """
        CREATE TRIGGER IF NOT EXISTS activities_ai AFTER INSERT ON activities BEGIN
            INSERT INTO activities_fts(content, activity_id, timestamp)
            VALUES (
                new.window_title || ' ' || 
                COALESCE(new.extracted_text, '') || ' ' ||
                new.app_name,
                new.id,
                new.timestamp
            );
        END
        """,

        """
        CREATE TRIGGER IF NOT EXISTS activities_ad AFTER DELETE ON activities BEGIN
            DELETE FROM activities_fts WHERE activity_id = old.id;
        END
        """,

        """
        CREATE TRIGGER IF NOT EXISTS activities_au AFTER UPDATE ON activities BEGIN
            DELETE FROM activities_fts WHERE activity_id = old.id;
            INSERT INTO activities_fts(content, activity_id, timestamp)
            VALUES (
                new.window_title || ' ' || 
                COALESCE(new.extracted_text, '') || ' ' ||
                new.app_name,
                new.id,
                new.timestamp
            );
        END
        """,

        # Pattern storage for learning
        """
        CREATE TABLE IF NOT EXISTS activity_patterns (
            id TEXT PRIMARY KEY,
            pattern_type TEXT NOT NULL,
            pattern_data TEXT NOT NULL,  -- JSON
            occurrence_count INTEGER DEFAULT 1,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            confidence REAL DEFAULT 1.0
        )
        """,

        # Assistant outputs table for storing assistant-session outputs (and
        # legacy 'regular'/'activity' rows persisted to the same store).
        # Renamed from 'suggestions'; the table-rename + column-rename
        # migrations live in schema_manager.
        """
        CREATE TABLE IF NOT EXISTS assistant_outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id TEXT,
            output_text TEXT NOT NULL,
            context_text TEXT,
            explanation_text TEXT,
            model_name TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            was_inserted BOOLEAN DEFAULT FALSE,
            insertion_timestamp TIMESTAMP,
            user_rating INTEGER CHECK (user_rating BETWEEN 1 AND 5),
            user_feedback TEXT,
            user_request TEXT,

            -- History columns (v0.7.0)
            output_type TEXT DEFAULT 'regular',  -- 'assistant_session' (legacy 'voice' rows are migrated on startup), 'regular', or 'activity'
            screen_capture_path TEXT,
            text_selection TEXT,
            app_name TEXT,
            window_title TEXT,
            status TEXT DEFAULT 'completed',
            refinement_count INTEGER DEFAULT 0,
            refinements TEXT,  -- JSON array of refinement entries
            processing_time_ms INTEGER,

            -- Input modality for AssistantSession rows: 'voice', 'text', or NULL.
            -- NULL means modality is unknown (legacy rows pre-migration) or
            -- not applicable (screen-only / NO_INSTRUCTION_DEFAULT path).
            input_modality TEXT,

            -- Writing-sample context captured from the live session so History can save samples later.
            context_type TEXT,
            recipient TEXT,

            FOREIGN KEY (activity_id) REFERENCES activities(id)
        )
        """,

        # Agent tasks table for storing agent_task records with clarifications
        """
        CREATE TABLE IF NOT EXISTS agent_tasks (
            id TEXT PRIMARY KEY,
            timestamp TIMESTAMP NOT NULL,
            original_prompt TEXT NOT NULL,
            transcribed_prompt TEXT NOT NULL,
            display_prompt_markdown TEXT,
            confidence_score REAL,
            
            -- Context (preserved for clarifications)
            app_name TEXT,
            window_title TEXT,
            screen_text TEXT,
            screen_capture_path TEXT,
            
            -- Display
            title TEXT,  -- Short generated title for sidebar display (heuristic on create, LLM-refined on completion)

            -- Provenance: which application surface created this task. NULL means
            -- directly user-initiated (voice/manual capture).
            origin_type TEXT,  -- NULL | 'conversation' | 'scheduled_task' | 'todo' | 'todo_workspace'
            origin_id TEXT,    -- conversation_id or scheduled_agent_task_id, per origin_type
            
            -- Processing
            operation TEXT,
            operation_confidence REAL,
            operation_parameters TEXT,  -- JSON
            result_data TEXT,  -- JSON
            
            -- Status
            status TEXT NOT NULL DEFAULT 'processing',
            processing_time_ms INTEGER,
            
            -- Clarifications as JSON array
            clarifications TEXT,  -- JSON: [{"request": "...", "response": "...", "timestamp": "..."}]
            
            -- Task chain fields (links task turns in same UI thread)
            root_task_id TEXT,  -- Stable ID of the root task in this thread; equal to id for root rows
            previous_task_id TEXT,  -- Immediate predecessor turn; NULL for root rows
            chain_sequence_number INTEGER DEFAULT 0,  -- 0 for root, 1+ for follow-ups in order
            
            -- Session fields (used for both manual chains and agent-planned workflows)
            session_type TEXT,  -- NULL='standalone', 'chain'='manual follow-ups', 'collaborative'='agent-planned workflow'
            session_status TEXT,  -- NULL, 'planning', 'active', 'waiting_input', 'waiting_approval', 'continuing', 'completed', 'canceled', 'failed'
            workflow_plan TEXT,  -- JSON: Array of planned steps with checkpoint configurations (NULL for simple/chain agent tasks)
            current_step INTEGER,  -- Current step index (for collaborative workflows)
            total_planned_steps INTEGER,  -- Total steps planned (for collaborative workflows)
            completed_steps TEXT,  -- JSON: Array of completed step results (used by chains AND collaborative)
            pending_steps TEXT,  -- JSON: Array of remaining steps (for collaborative workflows)
            accumulated_artifacts TEXT,  -- JSON: Files, data, outputs from previous steps (used by chains AND collaborative)
            last_interaction_timestamp TIMESTAMP,  -- Last user interaction timestamp
            interaction_count INTEGER DEFAULT 0,  -- Number of user interactions/checkpoints
            
            -- Execution timeline (unified chronological log of thinking + steps + tool calls)
            execution_timeline TEXT,  -- JSON: [{type, timestamp, content, ...}] ordered by occurrence

            -- Sidebar/search summary fields maintained on root rows for fast history browsing
            last_turn_timestamp TIMESTAMP,
            turn_count INTEGER DEFAULT 1,
            follow_up_count INTEGER DEFAULT 0,
            result_preview TEXT,
            file_count INTEGER DEFAULT 0,
            latest_status TEXT,
            latest_agent_task_id TEXT,
            
            -- User feedback
            user_rating INTEGER CHECK (user_rating BETWEEN 1 AND 5),
            user_feedback TEXT,
            
            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,

        # Scheduled agent task definitions
        """
        CREATE TABLE IF NOT EXISTS scheduled_agent_tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            agent_task_text TEXT NOT NULL,
            schedule_type TEXT NOT NULL, -- one_time | recurring
            schedule_config TEXT NOT NULL, -- JSON config (time/day/interval/etc)
            timezone TEXT DEFAULT 'UTC',
            is_active BOOLEAN DEFAULT TRUE,
            source_type TEXT DEFAULT 'manual', -- manual | smart
            reference_paths TEXT NOT NULL DEFAULT '[]', -- JSON array of attached file paths
            next_run_at TIMESTAMP,
            last_run_at TIMESTAMP,
            last_status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,

        # Scheduled run tracking (links schedule jobs to agent_task executions)
        """
        CREATE TABLE IF NOT EXISTS scheduled_agent_task_runs (
            id TEXT PRIMARY KEY,
            scheduled_agent_task_id TEXT NOT NULL,
            agent_task_id TEXT,
            scheduled_for TIMESTAMP NOT NULL,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'scheduled', -- scheduled | running | completed | failed | missed | skipped
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (scheduled_agent_task_id) REFERENCES scheduled_agent_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE SET NULL
        )
        """,

        # Session interactions - User feedback at collaborative checkpoints
        """
        CREATE TABLE IF NOT EXISTS session_interactions (
            id TEXT PRIMARY KEY,
            agent_task_id TEXT NOT NULL,
            interaction_type TEXT NOT NULL,  -- 'prompt', 'response', 'approval', 'modification'
            
            -- Content
            prompt_text TEXT,  -- What system asked
            user_response TEXT,  -- What user said/chose
            response_type TEXT,  -- 'voice', 'button', 'text_input', 'selection'
            
            -- Context
            step_index INTEGER,
            step_description TEXT,
            step_results TEXT,  -- JSON: Results at this checkpoint
            
            -- Approval tracking (for command execution approvals)
            requires_approval BOOLEAN DEFAULT FALSE,
            approval_status TEXT,  -- 'pending', 'approved', 'denied', 'modified'
            
            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE
        )
        """,

        # Conversations table for storing conversation metadata
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            -- Metadata
            system_message TEXT,
            title TEXT,  -- Optional conversation title
            metadata TEXT,  -- JSON for additional metadata
            
            -- Status
            is_active BOOLEAN DEFAULT TRUE,
            message_count INTEGER DEFAULT 0
        )
        """,

        # Messages table for storing individual messages within conversations
        """
        CREATE TABLE IF NOT EXISTS conversation_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'error')),
            content TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            -- Message metadata
            model_id TEXT,  -- Which model generated this message (for assistant messages)
            metadata TEXT,  -- JSON for additional message metadata
            
            -- Performance tracking
            processing_time_ms INTEGER,  -- How long it took to generate (for assistant messages)
            token_count INTEGER,  -- Number of tokens in the message
            
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
        """,

        # Indices for performance
        """
        CREATE INDEX IF NOT EXISTS idx_activities_timestamp 
        ON activities(timestamp)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_activities_app_name 
        ON activities(app_name)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_activities_context 
        ON activities(context_hash)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_conversations_created_at 
        ON conversations(created_at)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_conversations_updated_at 
        ON conversations(updated_at)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_conversations_updated_at_id
        ON conversations(updated_at DESC, id DESC)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_id 
        ON conversation_messages(conversation_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_conversation_messages_timestamp 
        ON conversation_messages(timestamp)
        """,

        # Workflow todo indices for efficient workflow execution
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_todos_agent_task_id 
        ON workflow_todos(agent_task_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_workflow_todos_status 
        ON workflow_todos(status)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_workflow_todos_created_at 
        ON workflow_todos(created_at)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_todo_steps_todo_id 
        ON todo_steps(todo_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_todo_steps_status 
        ON todo_steps(status)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_todo_steps_step_number 
        ON todo_steps(todo_id, step_number)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_conversation_messages_role 
        ON conversation_messages(role)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_metadata_key_value 
        ON activity_metadata(key, value)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_patterns_type 
        ON activity_patterns(pattern_type)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_assistant_outputs_activity_id 
        ON assistant_outputs(activity_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_assistant_outputs_rating 
        ON assistant_outputs(user_rating)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_assistant_outputs_generated_at
        ON assistant_outputs(generated_at)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_transcriptions_timestamp 
        ON transcriptions(timestamp)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_timestamp 
        ON agent_tasks(timestamp)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_status 
        ON agent_tasks(status)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_app_name 
        ON agent_tasks(app_name)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_session_status 
        ON agent_tasks(session_status)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_root_sequence
        ON agent_tasks(root_task_id, chain_sequence_number)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_last_turn
        ON agent_tasks(last_turn_timestamp DESC)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_conversation_roots
        ON agent_tasks(origin_type, origin_id, last_turn_timestamp DESC)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_agent_tasks_latest_status
        ON agent_tasks(latest_status)
        """,

        """
        CREATE VIRTUAL TABLE IF NOT EXISTS agent_task_search_fts USING fts5(
            root_task_id UNINDEXED,
            content,
            tokenize='porter unicode61'
        )
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_session_interactions_agent_task_id 
        ON session_interactions(agent_task_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_session_interactions_type 
        ON session_interactions(interaction_type)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_session_interactions_created_at 
        ON session_interactions(created_at)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_scheduled_agent_tasks_active_next_run
        ON scheduled_agent_tasks(is_active, next_run_at)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_scheduled_agent_tasks_updated_at
        ON scheduled_agent_tasks(updated_at)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_scheduled_agent_task_runs_schedule
        ON scheduled_agent_task_runs(scheduled_agent_task_id, scheduled_for DESC)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_scheduled_agent_task_runs_agent_task
        ON scheduled_agent_task_runs(agent_task_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_scheduled_agent_task_runs_status
        ON scheduled_agent_task_runs(status, scheduled_for)
        """,

        # MCP connector call log - per-call audit trail for every external MCP
        # tool dispatch routed through the `external_catalog` agent tool.
        # Persists name + arguments + outcome so the user can review what their
        # agent did on their behalf via remote connectors. Foreign keys are
        # nullable because dispatches outside an active agent_task (e.g. the
        # Settings UI's "test connection" probe) still produce log entries.
        """
        CREATE TABLE IF NOT EXISTS mcp_call_log (
            id TEXT PRIMARY KEY,
            connection_id TEXT NOT NULL,
            server_url TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            arguments_json TEXT,           -- JSON of the args passed to the tool
            result_classification TEXT NOT NULL, -- success | error | denied | skipped
            error_kind TEXT,                -- normalized error envelope kind, when result_classification != 'success'
            error_message TEXT,             -- human-readable error, optional
            content_preview TEXT,           -- first ~200 chars of the result content for the audit-log UI
            started_at TIMESTAMP NOT NULL,
            completed_at TIMESTAMP,
            agent_task_id TEXT                 -- nullable: same reason
        )
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_mcp_call_log_started_at
        ON mcp_call_log(started_at DESC)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_mcp_call_log_connection
        ON mcp_call_log(connection_id, started_at DESC)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_mcp_call_log_agent_task
        ON mcp_call_log(agent_task_id)
        """,

        # ============================================================================
        # PERSONALIZATION TABLES - User profile and communication style learning
        # ============================================================================

        # User profile table
        """
        CREATE TABLE IF NOT EXISTS user_profile (
            id TEXT PRIMARY KEY DEFAULT 'default',
            
            -- Identity
            full_name TEXT,
            preferred_name TEXT,
            email TEXT,
            
            -- Professional context
            job_title TEXT,
            company_name TEXT,
            industry TEXT,
            
            -- Communication preferences
            default_formality TEXT,
            default_tone TEXT,
            custom_instructions TEXT,
            
            -- Metadata
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            profile_version INTEGER DEFAULT 1
        )
        """,

        # Communication style profile table
        """
        CREATE TABLE IF NOT EXISTS communication_style_profile (
            id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'default',
            context_type TEXT NOT NULL,
            
            -- Style attributes (JSON)
            style_attributes TEXT NOT NULL,
            
            -- Confidence and sample size
            confidence REAL DEFAULT 0.0,
            sample_count INTEGER DEFAULT 0,
            
            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP,
            
            FOREIGN KEY (user_id) REFERENCES user_profile(id)
        )
        """,

        # Writing samples table
        """
        CREATE TABLE IF NOT EXISTS writing_samples (
            id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'default',
            
            -- Sample metadata
            source_type TEXT NOT NULL,
            context_type TEXT NOT NULL,
            app_name TEXT,
            
            -- The actual writing
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            
            -- Context about the writing
            recipient TEXT,
            subject TEXT,
            relationship_type TEXT,
            
            -- Edit tracking (for future analysis)
            was_edited BOOLEAN DEFAULT FALSE,
            edit_distance INTEGER,

            -- Assistant History row this sample was saved from, when known
            assistant_output_id INTEGER,
            
            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (user_id) REFERENCES user_profile(id)
        )
        """,

        # Contact relationships table
        """
        CREATE TABLE IF NOT EXISTS contact_relationships (
            id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'default',
            
            -- Contact identity
            contact_name TEXT,
            contact_email TEXT NOT NULL,
            contact_company TEXT,
            
            -- Relationship metadata
            relationship_type TEXT DEFAULT 'unknown',
            formality_level TEXT DEFAULT 'professional',
            
            -- Communication patterns
            message_count INTEGER DEFAULT 0,
            last_contact_date TIMESTAMP,
            typical_response_time_hours REAL,
            
            -- Context (JSON)
            common_topics TEXT,
            notes TEXT,
            
            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (user_id) REFERENCES user_profile(id)
        )
        """,

        # User signatures table
        """
        CREATE TABLE IF NOT EXISTS user_signatures (
            id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'default',
            
            -- Signature content
            signature_text TEXT NOT NULL,
            signature_html TEXT,
            
            -- Usage context
            context TEXT DEFAULT 'default',
            is_primary BOOLEAN DEFAULT FALSE,
            
            -- Detection metadata
            first_seen TIMESTAMP NOT NULL,
            last_seen TIMESTAMP NOT NULL,
            occurrence_count INTEGER DEFAULT 1,
            confidence REAL DEFAULT 1.0,
            
            FOREIGN KEY (user_id) REFERENCES user_profile(id)
        )
        """,

        # Personalization insights table
        """
        CREATE TABLE IF NOT EXISTS personalization_insights (
            id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'default',
            
            -- Insight metadata
            insight_type TEXT NOT NULL,
            context_type TEXT,
            
            -- The insight
            insight_key TEXT NOT NULL,
            insight_value TEXT NOT NULL,
            
            -- Confidence and usage
            confidence REAL DEFAULT 0.0,
            times_applied INTEGER DEFAULT 0,
            success_rate REAL,
            
            -- Source tracking
            derived_from TEXT NOT NULL,
            
            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (user_id) REFERENCES user_profile(id)
        )
        """,

        # Indices for personalization tables
        """
        CREATE INDEX IF NOT EXISTS idx_comm_style_context 
        ON communication_style_profile(user_id, context_type)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_writing_samples_type 
        ON writing_samples(user_id, context_type)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_writing_samples_source 
        ON writing_samples(source_type)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_writing_samples_hash 
        ON writing_samples(content_hash)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_writing_samples_assistant_output
        ON writing_samples(assistant_output_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_contacts_email 
        ON contact_relationships(user_id, contact_email)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_contacts_relationship 
        ON contact_relationships(relationship_type)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_signatures_primary 
        ON user_signatures(user_id, is_primary)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_insights_type 
        ON personalization_insights(user_id, insight_type, context_type)
        """,

        # Contact identity observations table.
        # Holds candidate identity facts discovered by Activity Capture
        # post-processing. This is intentionally separate from
        # contact_relationships: observations are unverified, screen-derived
        # candidates and must never by themselves assert a relationship.
        """
        CREATE TABLE IF NOT EXISTS contact_identity_observations (
            id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'default',

            -- Provenance of the observation
            source_type TEXT NOT NULL,
            source_activity_id TEXT,
            source_app_name TEXT,
            source_window_title TEXT,

            -- Observed identity facts (no relationship inference)
            normalized_email TEXT NOT NULL,
            display_name TEXT,
            organization_name TEXT,
            job_title TEXT,
            relationship_hint TEXT,

            -- Extraction quality
            confidence REAL DEFAULT 0.0,
            reason TEXT,
            raw_evidence TEXT,

            -- Aggregation tracking
            occurrence_count INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id) REFERENCES user_profile(id)
        )
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_contact_observations_email
        ON contact_identity_observations(user_id, normalized_email)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_contact_observations_activity
        ON contact_identity_observations(source_activity_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_contact_observations_confidence
        ON contact_identity_observations(confidence)
        """,

        # To-Do domain - durable items, sources, and audit events
        """
        CREATE TABLE IF NOT EXISTS todo_items (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 240),
            description TEXT NOT NULL DEFAULT '' CHECK(length(description) <= 12000),
            notes TEXT NOT NULL DEFAULT '' CHECK(length(notes) <= 12000),
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('candidate', 'open', 'in_progress', 'ready_for_review', 'completed', 'dismissed', 'canceled')),
            responsibility TEXT NOT NULL DEFAULT 'unspecified' CHECK(responsibility IN ('user', 'agent', 'shared', 'unspecified')),
            priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('low', 'normal', 'high')),
            due_at TEXT,
            completed_at TEXT,
            idempotency_key TEXT,
            idempotency_payload_hash TEXT,
            revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
            created_by_kind TEXT NOT NULL,
            created_by_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS todo_sources (
            id TEXT PRIMARY KEY,
            todo_id TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_locator_json TEXT NOT NULL DEFAULT '{}',
            source_excerpt TEXT NOT NULL DEFAULT '',
            created_by_kind TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(todo_id) REFERENCES todo_items(id) ON DELETE CASCADE,
            UNIQUE(source_kind, source_id)
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS todo_references (
            id TEXT PRIMARY KEY,
            todo_id TEXT NOT NULL,
            path TEXT NOT NULL CHECK(length(trim(path)) BETWEEN 1 AND 4096),
            created_by_kind TEXT NOT NULL,
            created_by_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(todo_id) REFERENCES todo_items(id) ON DELETE CASCADE,
            UNIQUE(todo_id, path)
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS todo_events (
            id TEXT PRIMARY KEY,
            todo_id TEXT NOT NULL,
            event_kind TEXT NOT NULL,
            actor_kind TEXT NOT NULL,
            actor_id TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(todo_id) REFERENCES todo_items(id) ON DELETE CASCADE
        )
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_todo_items_status_updated_at ON todo_items(status, updated_at DESC)
        """,

        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_todo_items_idempotency_key ON todo_items(idempotency_key) WHERE idempotency_key IS NOT NULL
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_todo_sources_todo_id_created_at ON todo_sources(todo_id, created_at)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_todo_references_todo_id_created_at ON todo_references(todo_id, created_at)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_todo_events_todo_id_created_at ON todo_events(todo_id, created_at)
        """,

        # BasilBoard - declarative tab registry
        """
        CREATE TABLE IF NOT EXISTS basil_board_tabs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            icon_key TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            tab_kind TEXT NOT NULL CHECK (tab_kind IN ('home', 'capability', 'system_embed', 'agent_report')),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
            configuration_json TEXT NOT NULL DEFAULT '{}',
            created_by_kind TEXT NOT NULL DEFAULT 'system',
            created_by_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,

        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_basil_board_tabs_active_home
        ON basil_board_tabs(tab_kind)
        WHERE tab_kind = 'home' AND status = 'active'
        """,

        """
        CREATE TABLE IF NOT EXISTS basil_board_home_state (
            id TEXT PRIMARY KEY CHECK (id = 'default'),
            conversation_id TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS basil_board_home_turns (
            user_message_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            route_kind TEXT NOT NULL CHECK (route_kind IN ('conversation', 'agent_task')),
            route_reason TEXT NOT NULL,
            route_confidence REAL,
            agent_task_id TEXT UNIQUE,
            assistant_message_id TEXT,
            state TEXT NOT NULL CHECK (state IN ('routing', 'running', 'completed', 'failed', 'canceled')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (user_message_id) REFERENCES conversation_messages(id)
        )
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_basil_board_home_turns_conversation
        ON basil_board_home_turns(conversation_id, created_at)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_basil_board_home_turns_agent_task
        ON basil_board_home_turns(agent_task_id)
        WHERE agent_task_id IS NOT NULL
        """,

        """
        CREATE TABLE IF NOT EXISTS basil_board_inquiries (
            id TEXT PRIMARY KEY,
            prompt_text TEXT NOT NULL,
            display_prompt_markdown TEXT,
            reference_paths_json TEXT NOT NULL DEFAULT '[]',
            route_kind TEXT CHECK (route_kind IN ('conversation', 'agent_task')),
            route_reason TEXT,
            route_confidence REAL,
            state TEXT NOT NULL DEFAULT 'routing' CHECK (state IN ('routing', 'running', 'completed', 'failed', 'canceled')),
            conversation_id TEXT,
            user_message_id TEXT UNIQUE,
            assistant_message_id TEXT,
            agent_task_id TEXT UNIQUE,
            legacy_imported INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (user_message_id) REFERENCES conversation_messages(id),
            FOREIGN KEY (assistant_message_id) REFERENCES conversation_messages(id)
        )
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_basil_board_inquiries_updated
        ON basil_board_inquiries(updated_at DESC)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_basil_board_inquiries_agent_task
        ON basil_board_inquiries(agent_task_id)
        WHERE agent_task_id IS NOT NULL
        """,

        """
        CREATE TABLE IF NOT EXISTS basil_board_artifacts (
            id TEXT PRIMARY KEY,
            tab_id TEXT NOT NULL,
            artifact_kind TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            source_refs_json TEXT NOT NULL DEFAULT '[]',
            coverage_json TEXT NOT NULL DEFAULT '{}',
            owner_task_id TEXT,
            owner_run_id TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tab_id) REFERENCES basil_board_tabs(id) ON DELETE CASCADE
        )
        """,
    ]

# Enum-style constants for common metadata keys
class MetadataKeys:
    CLIENT = "client"
    PROJECT = "project"
    TASK = "task"
    LANGUAGE = "language"
    DOMAIN = "domain"
    CATEGORY = "category"

# Pattern types for learning system
class PatternTypes:
    TEMPORAL = "temporal"      # Time-based patterns
    CONTEXTUAL = "contextual"  # Context-based patterns
    SEQUENCE = "sequence"      # Activity sequence patterns
    CLIENT = "client"         # Client-specific patterns
    PROJECT = "project"       # Project-specific patterns