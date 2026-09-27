# Basil Development Principles

This document outlines key architectural decisions and development patterns that should be followed when working on the Basil codebase.

## Signal Handling and Event Management

### Principle: Distinct Signal Chains for Distinct Operations

**Context**: When handling different hotkey operations (F9-F12) that trigger different UI behaviors, we initially used generic signals (processing_started, processing_completed) which led to unintended cross-talk between operations.

**Pattern to Follow**:
1. Create separate, dedicated signal chains for each distinct operation type
2. Never reuse signals across different operation types
3. Name signals explicitly after their operation (e.g., `capture_started`, `suggestion_ready`)

**Example Implementation**:
```python
class HotkeyProcessor(QObject):
    # Capture-specific signals (F10)
    capture_started = pyqtSignal(str)
    capture_completed = pyqtSignal(str)
    
    # Suggestion-specific signals (F11)
    suggestion_started = pyqtSignal(str)
    suggestion_completed = pyqtSignal(str)
    suggestion_ready = pyqtSignal(str)
    
    # Insertion signals (F12)
    suggestion_inserted = pyqtSignal()
    
    # Conversation signals (F9)
    conversation_toggled = pyqtSignal(bool)
```

**What Not to Do**:
- Don't use generic signals (e.g., `processing_started`) for different operation types
- Don't try to filter or route generic signals based on message content or operation flags
- Don't attempt to reuse signals across different operation types, even if they seem similar

**Benefits**:
1. Clear, traceable signal flow for each operation
2. No unintended cross-talk between different operations
3. Easier debugging as each operation has its own distinct signal chain
4. More maintainable code as operation types are clearly separated

**When to Apply**:
- When implementing new features that involve different types of operations
- When different UI components need to respond to different operations
- When operations are fundamentally distinct in their purpose or behavior

## Class and Method Naming Conventions

### Principle: Explicit and Distinct Names for Classes and Methods

**Context**: In a complex application with multiple services and processors, using generic or ambiguous names can lead to confusion, naming conflicts, and difficulty in understanding the purpose of different components. We've encountered issues where similar method names across different classes (e.g., `process_query`) led to confusion about parameter requirements and functionality.

**Pattern to Follow**:
1. Use specific, descriptive prefixes for different types of operations:
   - `process_` for data transformation
   - `handle_` for event responses
   - `initialize_` or `init_` for setup
   - `validate_` for checks
2. Include the domain/context in class names
3. Use verb-noun combinations that clearly indicate purpose
4. Suffix processor/handler classes with their role

**Example Implementation**:
```python
# Instead of generic QueryProcessor
class ActivityQueryProcessor:
    async def process_activity_query(self, query_text: str) -> QueryResult:
        pass

# Instead of generic IntentHandler
class QueryIntentHandler:
    async def interpret_user_query(self, query_text: str) -> Dict[str, Any]:
        pass
    
    async def format_query_response(self, results: QueryResult) -> str:
        pass
```

**What Not to Do**:
- Don't use generic method names like `process()` or `handle()`
- Don't reuse method names across different contexts without proper qualification
- Don't abbreviate unless absolutely necessary
- Don't use ambiguous terms that could apply to multiple operations

**Benefits**:
1. Self-documenting code through clear naming
2. Reduced confusion about method purpose and requirements
3. Easier code navigation and search
4. Better IDE auto-completion support
5. Clearer stack traces during debugging

**When to Apply**:
- When creating new classes or methods
- When refactoring existing code for clarity
- When similar operations exist across different contexts
- When methods could be confused with standard library methods

## Scope Management and Task Focus

### Principle: Strict Adherence to Requested Changes

**Context**: When implementing new features or fixing bugs, there's often a temptation to "improve" unrelated code or perform broader refactoring. This can lead to unintended side effects, increased testing burden, and scope creep. Additionally, existing code comments often provide valuable context and improve readability, even if they might not match current documentation preferences.

**Pattern to Follow**:
1. Only modify code directly related to the requested change
2. Document potential improvements separately for future consideration
3. Focus on completing the specific task at hand
4. Resist the urge to "clean up" unrelated code
5. Propose broader changes as separate tasks
6. Preserve existing code comments unless:
   - They are explicitly part of the requested changes
   - They are demonstrably incorrect
   - The code they describe is being removed/replaced

**What Not to Do**:
- Don't perform unrelated refactoring while implementing a feature
- Don't change existing method signatures unless explicitly requested
- Don't "improve" code that isn't part of the current task
- Don't introduce new patterns without discussion
- Don't modify working code that's unrelated to your task
- Don't remove or modify existing comments just because:
  - They don't match your preferred style
  - You think the code is "self-documenting"
  - You would have written them differently
  - They seem redundant to you
  - You're changing nearby code

**Benefits**:
1. Clearer code review process
2. Reduced risk of unintended side effects
3. Better tracking of changes and their purposes
4. More focused testing requirements
5. Improved stability and predictability
6. Preserved historical context and understanding
7. Maintained readability for all team members

**When to Apply**:
- When implementing new features
- When fixing bugs
- When making performance improvements
- When updating documentation
- When refactoring specific components
- When working with heavily commented code
- When modifying complex algorithms or business logic

## Method Naming Stability

### Principle: Preserve Existing Method Names and Signatures

**Context**: Changing method names or signatures, even with good intentions, can lead to widespread compilation errors, broken references, and significant debugging time. We've experienced issues where implementing new functionality was complicated by simultaneous method name changes.

**Pattern to Follow**:
1. Keep existing method names unless explicitly requested to change them
2. If a method name must be changed:
   - Get explicit confirmation first
   - Use IDE refactoring tools to update all references
   - Document all affected components
   - Test thoroughly before committing
3. When adding new methods, ensure names don't conflict with existing ones
4. Use clear versioning if a method needs a new signature (e.g., `method_v2`)

**Example Implementation**:
```python
# Instead of renaming existing method:
def process_query(self, query: str) -> QueryResult:
    # Original implementation
    pass

# If new functionality is needed, add new method:
def process_query_v2(self, query: str, context: Optional[Dict] = None) -> QueryResult:
    # New implementation
    pass

# Or use clear, different name:
def process_query_with_context(self, query: str, context: Dict) -> QueryResult:
    # New implementation
    pass
```

**What Not to Do**:
- Don't rename methods without explicit request and approval
- Don't change method signatures as part of unrelated changes
- Don't introduce breaking changes to existing method contracts
- Don't duplicate method names with different signatures
- Don't remove or deprecate methods without thorough impact analysis

**Benefits**:
1. Reduced compilation errors
2. Easier code review process
3. Better backward compatibility
4. Clearer change tracking
5. Less debugging time
6. More stable codebase

**When to Apply**:
- When adding new functionality
- When extending existing methods
- When fixing bugs
- When improving performance
- When refactoring code

## Access Level Philosophy

### Principle: Pragmatic Access Levels for Application Code

**Context**: Traditional OOP principles often advocate for maximum encapsulation ("make everything as private as possible"). While this makes sense for public frameworks, it can create unnecessary friction in application development where we control both sides of every interface. We've encountered numerous issues where overly restrictive access levels led to compilation errors, awkward workarounds, and increased development time without providing tangible benefits.

**Pattern to Follow**:
1. Use internal (default) access level for application code unless there's a specific reason not to
2. Reserve private for truly internal implementation details that should never be accessed externally
3. Consider the practical implications of access levels rather than following dogmatic rules
4. Remember that the module boundary (internal) already provides encapsulation from external code
5. Focus encapsulation efforts on public APIs and framework boundaries

**Example Implementation**:
```swift
// Instead of making everything private by default:
class ApplicationController {
    // Internal by default - accessible within the module
    var statusManager: StatusManager
    var windowController: WindowController
    
    // Private because it's truly an implementation detail
    private var cleanupTimer: Timer?
    
    // Internal methods that other components might legitimately need
    func refreshState() { }
    func handleSystemEvent(_ event: Event) { }
}
```

**What Not to Do**:
- Don't make properties private just because they "could be"
- Don't create public accessors just to work around overly restrictive access
- Don't treat application components with the same level of paranoia as public framework code
- Don't sacrifice code clarity and maintainability for theoretical encapsulation benefits
- Don't force other developers to copy-paste or duplicate code just because of access restrictions

**Benefits**:
1. Reduced compilation errors and friction during development
2. More flexible and maintainable codebase
3. Easier testing without excessive test-only APIs
4. Better code reuse within the application
5. Clearer distinction between true implementation details and usable components
6. More time spent on actual features instead of fighting the type system

**When to Apply**:
- When working on application-level code (vs framework code)
- When multiple components need to coordinate
- When testing needs access to internal state
- When the cost of strict encapsulation outweighs its benefits
- When you find yourself creating public APIs just to work around access restrictions

## Avoiding Hardcoded Example Values

### Principle: Never Hardcode Example or Default Values

**Context**: There's a persistent tendency to take example values (like F8 for a hotkey) or default configurations and treat them as fixed values in the code. This creates brittle implementations that break when users want to customize these values, which they absolutely should be able to do.

**Pattern to Follow**:
1. Always use the actual configured/provided values in code, not examples
2. Treat all user-configurable values as dynamic, even if there's a common default
3. Use meaningful variable names that describe the purpose, not the value
4. Log the actual values being used, not assumed ones
5. Document the configurable nature of values in comments
6. Test with different values than the defaults

**Example Implementation**:
```swift
// WRONG - Hardcoding example value
print("F8 pressed - Transcription hotkey")

// RIGHT - Using actual configured value
print("\(binding.key) pressed - Transcription hotkey")

// WRONG - Assuming default dimensions
let defaultSize = CGSize(width: 400, height: 300)

// RIGHT - Making dimensions configurable
let windowSize = preferences.getWindowSize(defaultWidth: 400, defaultHeight: 300)
```

**What Not to Do**:
- Don't hardcode example values from documentation or user discussions
- Don't assume default values will remain constant
- Don't use literal values in logging or error messages
- Don't build logic that only works with specific values
- Don't copy-paste example code without making values configurable
- Don't treat user preferences as fixed constants

**Benefits**:
1. More flexible and maintainable code
2. Better user customization support
3. Easier testing with different configurations
4. More accurate logging and debugging
5. Reduced need for code changes when defaults change
6. Better separation of configuration from logic

**When to Apply**:
- When implementing any user-configurable feature
- When logging or displaying values to users
- When handling input or configuration values
- When writing tests
- When documenting code behavior
- When reviewing pull requests

**Real World Examples**:
1. Hotkeys: Users should be able to bind any key
2. Window sizes: Should be user-configurable
3. File paths: Should work with any valid path
4. Time intervals: Should be configurable
5. Color schemes: Should support custom colors
6. Default values: Should be overridable

**Impact of Violations**:
1. Reduced software flexibility
2. Increased support burden
3. Frustrated users unable to customize
4. Brittle code that breaks with configuration changes
5. Repeated code modifications for simple changes
6. Poor testing coverage due to fixed assumptions

Remember: If you find yourself typing a specific value that came from documentation, user discussion, or "common usage", stop and make it configurable instead.

## Code Comments and Documentation

1. **Comment Preservation**: Existing comments should be preserved unless:
   - Explicitly requested to modify or remove them
   - The code they describe is being removed
   - The comments are factually incorrect due to code changes

2. **Comment Value**: Comments often contain important context, rationale, and warnings that may not be immediately apparent from the code itself. Preserving them maintains this institutional knowledge.

3. **Comment Updates**: When making changes that affect commented code:
   - Update the comment if it becomes incorrect
   - Add new comments for significant changes
   - Do not remove or modify existing accurate comments

## State-Based Completion Detection

### Principle: Use State Changes, Not Arbitrary Timeouts

**Context**: There's a common anti-pattern of using arbitrary timeouts (e.g., "wait 3 seconds") when waiting for operations to complete, even when proper state changes or events are available. This leads to brittle code that either waits too long (hurting performance) or not long enough (causing race conditions).

**Pattern to Follow**:
1. Always prefer waiting for specific state changes or events over timeouts
2. Use completion handlers, callbacks, or state observers to detect when operations finish
3. Only use timeouts as a last resort when:
   - No state information is available
   - The operation has no defined completion event
   - Required for safety/deadlock prevention

**Example Implementation**:
```swift
// WRONG - Arbitrary timeout
func waitForOperation() async {
    await operation.start()
    try? await Task.sleep(nanoseconds: 3_000_000_000) // 3 second guess
}

// RIGHT - State-based completion
func waitForOperation() async {
    await withCheckedContinuation { continuation in
        operation.onComplete = {
            continuation.resume()
        }
        operation.start()
    }
}
```

**What Not to Do**:
- Don't use arbitrary sleep/delay times
- Don't guess how long operations "should" take
- Don't use timeouts when state changes are available
- Don't mix timeouts with state detection unless absolutely necessary
- Don't assume operations always take the same amount of time

**Benefits**:
1. More reliable code that adapts to actual conditions
2. Better performance by not waiting longer than necessary
3. Fewer race conditions and timing-related bugs
4. More predictable behavior across different systems
5. Easier testing and debugging

**When to Apply**:
- When implementing shutdown sequences
- When waiting for operations to complete
- When handling asynchronous operations
- When coordinating between multiple services
- When dealing with network operations
- When managing resource cleanup

**Real World Examples**:
1. Shutdown sequences: Wait for actual process termination signals
2. Network operations: Wait for connection closed events
3. File operations: Wait for file system notifications
4. Database operations: Wait for transaction completion
5. UI animations: Wait for animation completion callbacks
6. Service initialization: Wait for ready state signals

## Graceful Error Handling for Core Features

### Principle: Core Features Should Continue Working Despite Non-Critical Errors

**Context**: When implementing features that combine multiple operations (like transcription with database storage), errors in secondary operations (like database writes) should not prevent the primary functionality from working. We encountered issues where database errors would completely halt the transcription process, preventing users from accessing the core functionality.

**Pattern to Follow**:
1. Identify the primary vs. secondary operations in a feature
2. Wrap secondary operations in try/except blocks that log errors but don't propagate them
3. Ensure the primary operation can continue even if secondary operations fail
4. Provide meaningful error messages that help diagnose issues
5. When possible, extract useful information from exceptions to maintain functionality
6. Design systems with fallback behaviors for common failure modes

**Example Implementation**:
```python
async def transcribe_audio(audio_data: bytes) -> str:
    try:
        # Primary operation - must succeed
        transcription_text = await transcription_service.process_audio(audio_data)
        
        # Secondary operation - should not block primary functionality
        try:
            await transcription_repository.save_transcription(
                Transcription(
                    id=str(uuid.uuid4()),
                    timestamp=datetime.now(),
                    transcription_text=transcription_text,
                    audio_file_path=audio_path
                )
            )
        except Exception as e:
            logger.warning(f"Failed to save transcription to database: {e}")
            # Continue with transcription process despite database error
            
        return transcription_text
    except Exception as e:
        # Primary operation failed - must be handled or propagated
        logger.error(f"Transcription failed: {e}")
        raise
```

**What Not to Do**:
- Don't let secondary operation failures (like database errors) prevent primary functionality
- Don't silently catch errors without logging them
- Don't use overly broad exception handling without specific recovery strategies
- Don't assume all operations are equally critical
- Don't force users to restart or reconfigure when non-critical components fail

**Benefits**:
1. More robust applications that continue working despite partial failures
2. Better user experience with fewer complete failures
3. Easier diagnosis of issues through proper error logging
4. More resilient systems that can recover from common error conditions
5. Clearer separation between critical and non-critical operations

**When to Apply**:
- When implementing features with multiple components
- When integrating with external systems or databases
- When handling user-initiated actions that should rarely fail completely
- When designing systems that need high availability
- When working with operations that have different criticality levels

## Database Schema Initialization

### Principle: Components Should Initialize Their Required Database Schema

**Context**: When implementing features that require database storage, each component should ensure its required database schema exists before attempting operations. We encountered issues where the transcription feature would fail because it assumed tables existed without checking or creating them.

**Pattern to Follow**:
1. Each repository or data access component should check for and initialize its required schema
2. Schema initialization should happen during component initialization, not during operations
3. Schema checks should be efficient and only create tables/indexes if they don't exist
4. Schema versions should be tracked to support migrations when needed
5. Schema initialization should be idempotent (safe to run multiple times)

**Example Implementation**:
```python
class TranscriptionRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._initialize_db()
        
    def _initialize_db(self) -> None:
        """Initialize the database schema if needed."""
        conn = self._get_connection()
        try:
            # Check if table exists
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='transcriptions'"
            )
            if cursor.fetchone() is None:
                # Create table if it doesn't exist
                cursor.execute("""
                CREATE TABLE transcriptions (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    transcription_text TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    audio_file_path TEXT NOT NULL,
                    duration_seconds REAL,
                    language TEXT DEFAULT 'en',
                    created_at TEXT
                )
                """)
                cursor.execute(
                    "CREATE INDEX idx_transcriptions_timestamp ON transcriptions(timestamp)"
                )
                conn.commit()
                logger.info("Created transcriptions table and index")
        finally:
            conn.close()
```

**What Not to Do**:
- Don't assume database tables exist without checking
- Don't create tables during operation execution (too late)
- Don't perform expensive schema checks on every operation
- Don't fail silently if schema initialization fails
- Don't mix schema initialization with data operations

**Benefits**:
1. More robust applications that work correctly on first run
2. Self-initializing components that don't require manual setup
3. Clearer error messages when database issues occur
4. Better separation of initialization and operation concerns
5. Easier testing with clean database states

**When to Apply**:
- When implementing new database-backed features
- When creating repositories or data access components
- When designing systems that should work without manual setup
- When working with SQLite or other file-based databases
- When components have specific schema requirements

## Incremental Implementation

### Principle: Favor Small, Incremental Changes Over Large Modifications

**Context**: There's a tendency to implement large, sweeping changes that attempt to address multiple aspects of a feature at once. This often leads to complex, error-prone implementations that are difficult to test, debug, and review. We've experienced situations where large changes introduced subtle bugs that were challenging to isolate and fix.

**Pattern to Follow**:
1. Break large tasks into smaller, manageable chunks
2. Implement and test one aspect of a feature at a time
3. Make incremental commits that represent logical units of change
4. Ensure each change is functional and testable on its own
5. Build complex features progressively through working iterations

**Example Implementation**:
```python
# Instead of implementing an entire feature at once:

# Step 1: Add core data structure (commit #1)
class TranscriptionRecord:
    def __init__(self, text: str, timestamp: datetime):
        self.text = text
        self.timestamp = timestamp

# Step 2: Add storage mechanism (commit #2)
class TranscriptionStorage:
    def __init__(self):
        self.records = []
    
    def add_record(self, record: TranscriptionRecord):
        self.records.append(record)

# Step 3: Add retrieval functionality (commit #3)
def get_recent_records(self, limit: int = 10) -> List[TranscriptionRecord]:
    return sorted(self.records, key=lambda r: r.timestamp, reverse=True)[:limit]
```

**What Not to Do**:
- Don't attempt to implement an entire complex feature in one large change
- Don't mix core functionality with edge case handling in initial implementations
- Don't wait until everything is "perfect" before committing partial progress
- Don't hold up working features while trying to implement "nice-to-have" aspects
- Don't make changes across multiple subsystems in a single implementation

**Benefits**:
1. Easier code review and validation
2. More focused testing for each change
3. Reduced complexity in debugging and troubleshooting
4. Faster delivery of working functionality
5. More frequent integration with main codebase
6. Better visibility of progress and issues

**When to Apply**:
- When implementing complex or multi-faceted features
- When changes affect multiple subsystems
- When developing features with uncertain requirements
- When working on critical functionality where correctness is essential
- When changes involve significant refactoring or architectural modifications
- When multiple developers are working on related features

## Dependency Awareness

### Principle: Thoroughly Understand Dependencies Before Making Changes

**Context**: Code changes often have ripple effects through dependencies that aren't immediately obvious. We've encountered situations where seemingly simple changes broke functionality in unexpected places because dependencies weren't fully understood before implementation.

**Pattern to Follow**:
1. Identify all code that depends on the component being modified
2. Understand the contract/expectations these dependencies have
3. Map out potential impact before making changes
4. Use IDE tools to find all references to methods being modified
5. Check for implicit dependencies through inheritance or composition
6. Validate changes against all identified dependencies

**Example Implementation**:
```python
# Before modifying QueryProcessor.process_query:

# 1. Find all references to the method
# Using IDE tools or grep: grep -r "process_query" --include="*.py" ./

# 2. Document the dependencies
"""
Dependencies for QueryProcessor.process_query:
- ActivityService.handle_query calls process_query and expects QueryResult 
- QueryAPIHandler.POST uses process_query result for JSON serialization
- TranscriptionAnalyzer.analyze passes transcriptions to process_query
"""

# 3. Ensure changes maintain compatibility with all dependencies
def process_query(self, query: str) -> QueryResult:
    # Implementation changes can happen here, but must maintain:
    # - Return type compatibility (QueryResult)
    # - Input parameter expectations
    # - Performance characteristics relied upon by callers
    # - Error handling patterns expected by callers
```

**What Not to Do**:
- Don't modify methods without understanding their usage across the codebase
- Don't assume a component is only used where you expect it to be used
- Don't change method signatures without checking all call sites
- Don't modify behavior that dependencies might rely on
- Don't introduce new requirements (like configuration) without updating callers

**Benefits**:
1. Fewer regressions and broken functionality
2. More targeted and safer changes
3. Better understanding of system architecture
4. Reduced debugging time after changes
5. More accurate estimation of change complexity
6. Better preservation of system stability

**When to Apply**:
- Before modifying any shared or public methods
- When changing core components used across the system
- When refactoring code with potential callers elsewhere
- When modifying error handling or return types
- When changing performance characteristics
- When adding new requirements to existing methods

## Prioritization of Stability

### Principle: Working Code Trumps "Perfect" Code

**Context**: There's often a tension between making code "better" according to abstract principles and maintaining stable, working functionality. We've experienced situations where well-intentioned "improvements" to working code introduced bugs or incompatibilities that were difficult to track down.

**Pattern to Follow**:
1. Prioritize keeping working code working over aesthetic improvements
2. Make the smallest change necessary to achieve the requested functionality
3. Separate bug fixes from refactoring/improvements in different commits
4. Build on stable, proven components rather than rewriting them
5. When improvements are needed, propose them separately from functional changes
6. Value consistency and predictability over abstract "cleanliness"

**Example Implementation**:
```python
# Instead of rewriting working code for minor improvements:

# Original working function (leave intact unless specifically tasked with refactoring)
def get_user_data(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    data = cursor.fetchone()
    conn.close()
    return data

# If a specific improvement is needed, make minimal changes:
def get_user_data(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    data = cursor.fetchone()
    conn.close()
    
    # Only add the specific improvement needed (e.g., handling None case)
    if data is None:
        raise UserNotFoundError(f"User with ID {user_id} not found")
        
    return data
```

**What Not to Do**:
- Don't rewrite working code just to follow different patterns or styles
- Don't introduce speculative "improvements" to unrelated areas
- Don't prioritize elegance or theoretical benefits over proven stability
- Don't fix what isn't broken unless specifically tasked with doing so
- Don't introduce new abstractions without clear, immediate benefits

**Benefits**:
1. Greater system stability and reliability
2. Fewer regressions and unexpected side effects
3. Easier identification of issues when they occur
4. More predictable system behavior
5. Reduced development and debugging time
6. Preservation of institutional knowledge embedded in working code

**When to Apply**:
- When adding new features to existing systems
- When fixing specific bugs or issues
- When under time constraints to deliver working functionality
- When working with critical or complex systems
- When multiple developers maintain the same codebase
- When the risk of regression outweighs benefits of "improvement"

## Testing Before Refactoring

### Principle: Establish Tests Before Changing Implementation

**Context**: Refactoring or improving existing code without sufficient tests often leads to regressions and broken functionality. We've experienced situations where seemingly harmless changes caused issues that weren't immediately apparent because adequate tests weren't in place.

**Pattern to Follow**:
1. Before refactoring or changing implementation, ensure tests exist
2. If tests don't exist, write them first and verify they pass
3. Use tests as a safety net to validate changes don't break functionality
4. Separate test creation from implementation changes (different commits)
5. Prioritize functional correctness over code aesthetics
6. Verify tests fail appropriately when functionality is broken

**Example Implementation**:
```python
# Step 1: Add tests before refactoring (commit #1)
def test_user_authentication():
    # Test the current behavior
    user = authenticate_user("username", "password")
    assert user is not None
    assert user.id == expected_id
    
    # Test edge cases
    with pytest.raises(AuthenticationError):
        authenticate_user("username", "wrong_password")
    
    with pytest.raises(AuthenticationError):
        authenticate_user("nonexistent", "password")

# Step 2: Only after tests are in place and passing, refactor (commit #2)
def authenticate_user(username, password):
    # Refactored implementation can go here, with confidence
    # that the tests will catch any regressions
```

**What Not to Do**:
- Don't refactor or change implementation without tests in place
- Don't assume you understand all the current behavior without verification
- Don't mix test creation with implementation changes
- Don't prioritize cleaner code over functional correctness
- Don't skip testing edge cases and error conditions

**Benefits**:
1. Reduced likelihood of introducing regressions
2. Better understanding of current functionality before changing it
3. Increased confidence in changes
4. Documentation of expected behavior through tests
5. Easier debugging when issues occur
6. Progressive improvement of test coverage alongside changes

**When to Apply**:
- Before refactoring existing code
- When improving or optimizing implementations
- When changing complex or critical functionality
- When working with code you didn't write
- When changing code with potential side effects
- When multiple components depend on the behavior

---


Miscellaneous Considerations - 

* Before making any changes, first map out all the data flows for the affected feature."

* When a feature stops working after a model change, immediately trace the complete path of the affected data."

* For any model changes, explicitly check all consumers of that model in both frontend and backend."

* When a property access fails, search for ALL usages of that property path across the ENTIRE codebase.

* Before implementing model changes, generate a diff-style preview showing all required changes across files.

* When debugging data model-related issues, first verify the data structure at each layer

* For any API endpoint changes, list all frontend components that call that endpoint.

* Trace the call chain for starting a recording from hotkey press to audio capture"

*Compare the behavior between first recording and subsequent recordings, focusing on which code paths are taken



"trace the call chain"
"show all implementations"
"compare behavior between first and subsequent actions"
"list all entry points"


Consistent Prompting Strategies
Scope Definition Statement
Begin requests with: "Please limit your work strictly to [specific task] without modifying anything else."
Example: "Please limit your work strictly to adding the settings window resize capability without modifying any other functionality."
"Read-Only First" Approach
Start with: "First, just analyze without making changes, then propose a minimal solution."
This forces me to understand before acting.
Define a Change Budget
Specify limits: "Make no more than [X] line changes in [Y] files."
This creates clear boundaries for modifications.
"Safety Mode" Activation
Include: "Operate in safety mode: prefer minimal changes and explicit caution."
This keyword phrase could trigger a more conservative approach.
Reference Card
Create a shorthand: "Ref:MF" (Minimal Focus)
This would be a quick way to remind me of our agreement to stay narrowly focused.



Principles Check:
✓ Reviewed DEVELOPMENT_PRINCIPLES.md
✓ Following "Strict Adherence to Requested Changes" principle
✓ Maintaining existing method names and signatures
✓ Preserving existing comments
✓ Limiting changes to specifically requested functionality


@PRINCIPLES_CHECK: Review DEVELOPMENT_PRINCIPLES.md before making any changes.



_Note: This document should be updated with new principles as they are established. Each principle should include context, pattern to follow, example implementation, what not to do, benefits, and when to apply._ 