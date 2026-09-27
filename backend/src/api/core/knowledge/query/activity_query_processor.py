"""Process both structured and unstructured activity queries."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Set, Union, TypedDict
from enum import Enum, auto
import re
import logging
import json

logger = logging.getLogger(__name__)

class QueryStructure(Enum):
    """Internal classification of query structure level."""
    UNSTRUCTURED = auto()  # Free-form natural language
    SEMI_STRUCTURED = auto()  # Has some recognizable patterns
    STRUCTURED = auto()  # Matches known query patterns

class TimeRange(TypedDict, total=False):
    """Type definition for time range dictionary."""
    start: Union[str, datetime]
    end: Union[str, datetime]

@dataclass
class QueryResult:
    """Results from query processing."""
    activities: List[Dict[str, Any]]
    confidence: float
    timeframe: Optional[Dict[str, datetime]] = None
    grouping: Optional[str] = None
    summary: Optional[str] = None
    inferred_patterns: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'activities': self.activities,
            'confidence': self.confidence,
            'timeframe': {
                'start': self.timeframe['start'].isoformat() if self.timeframe and 'start' in self.timeframe else None,
                'end': self.timeframe['end'].isoformat() if self.timeframe and 'end' in self.timeframe else None
            } if self.timeframe else None,
            'grouping': self.grouping,
            'summary': self.summary,
            'inferred_patterns': self.inferred_patterns
        }

class ActivityQueryProcessor:
    """Process activity queries of varying structure levels."""
    
    def __init__(self, knowledge_base=None):
        """Initialize with a reference to the knowledge service.
        
        Args:
            knowledge_base: Service that provides access to activity data
        """
        self.knowledge_service = knowledge_base
        self._init_language_patterns()
    
    def _init_language_patterns(self):
        """Initialize regex patterns for query processing."""
        # Time-related patterns
        self.time_patterns = {
            'today': re.compile(r'\b(today|this day)\b', re.IGNORECASE),
            'yesterday': re.compile(r'\b(yesterday)\b', re.IGNORECASE),
            'this_week': re.compile(r'\b(this week|current week|the week)\b', re.IGNORECASE),
            'last_week': re.compile(r'\b(last week|previous week)\b', re.IGNORECASE),
            'this_month': re.compile(r'\b(this month|current month|the month)\b', re.IGNORECASE),
            'last_month': re.compile(r'\b(last month|previous month)\b', re.IGNORECASE),
            'n_days': re.compile(r'\b(in the last|past|previous)\s+(\d+)\s+(days?|weeks?|months?)\b', re.IGNORECASE),
            'specific_date': re.compile(r'\bon\s+(\d{1,2}(?:st|nd|rd|th)?[\s,]+(?:of\s+)?(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[\s,]+\d{1,2}(?:st|nd|rd|th)?)(?:[\s,]+\d{4})?\b', re.IGNORECASE),
            'time_range': re.compile(r'\bbetween\s+(.+?)\s+and\s+(.+?)\b', re.IGNORECASE),
            'morning': re.compile(r'\b(morning|mornings)\b', re.IGNORECASE),
            'afternoon': re.compile(r'\b(afternoon|afternoons)\b', re.IGNORECASE),
            'evening': re.compile(r'\b(evening|evenings)\b', re.IGNORECASE),
            'night': re.compile(r'\b(night|nights)\b', re.IGNORECASE),
        }
        
        # Action-related patterns
        self.action_patterns = {
            'worked_on': re.compile(r'\b(worked on|working on|did|doing|making|made|completed|finished|spent time on)\b', re.IGNORECASE),
            'used': re.compile(r'\b(used|using|opened|ran|executed|launched|started)\b', re.IGNORECASE),
            'viewed': re.compile(r'\b(viewed|watched|saw|looked at|observed|read)\b', re.IGNORECASE),
            'created': re.compile(r'\b(created|wrote|authored|composed|drafted)\b', re.IGNORECASE),
            'edited': re.compile(r'\b(edited|modified|changed|updated|revised|adjusted)\b', re.IGNORECASE),
            'searched': re.compile(r'\b(searched for|looked for|tried to find|sought|queried|googled)\b', re.IGNORECASE),
            'communicated': re.compile(r'\b(talked to|spoke with|chatted with|messaged|emailed|contacted|communicated with)\b', re.IGNORECASE),
        }
        
        # Context patterns
        self.context_patterns = {
            'in_app': re.compile(r'\b(in|using|with|on)\s+([A-Za-z0-9._-]+|\w+|\b(?:\w+\s+)+(?:app|application|program|software|editor|browser|terminal|ide))\b', re.IGNORECASE),
            'project': re.compile(r'\b(on project|for project|related to project|about project|project\s+named)\s+([A-Za-z0-9._-]+|\b(?:\w+\s)+)\b', re.IGNORECASE),
            'topic': re.compile(r'\b(about|regarding|concerning|related to|on the topic of|on)\s+([A-Za-z0-9._-]+|\b(?:\w+\s)+)\b', re.IGNORECASE),
        }
        
        # Structure patterns
        self.structure_patterns = {
            'list_query': re.compile(r'\b(list|show|display|get|find|what are|what were|give me)\b', re.IGNORECASE),
            'count_query': re.compile(r'\b(how many|count|number of|total)\b', re.IGNORECASE),
            'time_query': re.compile(r'\b(how long|how much time|duration|total time)\b', re.IGNORECASE),
            'summary_query': re.compile(r'\b(summarize|summary|overview|brief|summarize|synopsis|recap)\b', re.IGNORECASE),
        }
        
        # Known query patterns
        self.known_patterns = [
            re.compile(r'\b(what|list|show|tell me|display) (did I work on|was I doing|did I do)( \w+)?\b', re.IGNORECASE),
            re.compile(r'\b(how much time|how long) did I spend (on|using|with)( \w+)?\b', re.IGNORECASE),
            re.compile(r'\bshow me (all|my) activities (from|in|on|during)( \w+)?\b', re.IGNORECASE),
            re.compile(r'\b(what apps|which applications|what programs) did I use( \w+)?\b', re.IGNORECASE),
            re.compile(r'\b(summarize|give me a summary of) (my day|my activities|what I did|my work)( \w+)?\b', re.IGNORECASE),
        ]
    
    async def _search_activities_with_context(self, time_range, text_search, metadata_filters, limit):
        """Search activities with proper threading context handling."""
        import threading
        import asyncio
        import concurrent.futures
        
        current_thread = threading.current_thread()
        
        # Check if we're in ThreadPoolExecutor context (agent_task threading)
        if (current_thread.name.startswith('ThreadPoolExecutor') or 
            'run_agent_task_in_thread' in current_thread.name):
            logger.info("🔍 [ACTIVITY_SEARCH] Using ThreadPoolExecutor delegation for database call")
            
            # Use ThreadPoolExecutor to delegate the async call to a proper async context
            def sync_search_wrapper():
                """Synchronous wrapper for the async search call"""
                return asyncio.run(self.knowledge_service.search_activities(
                    time_range=time_range,
                    text_search=text_search,
                    metadata_filters=metadata_filters,
                    limit=limit
                ))
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(sync_search_wrapper)
                activities = future.result(timeout=30)  # 30 second timeout
                
            logger.info("🔍 [ACTIVITY_SEARCH] ThreadPoolExecutor delegation completed")
            return activities
        else:
            # Normal async context
            logger.info("🔍 [ACTIVITY_SEARCH] Using direct async call")
            return await self.knowledge_service.search_activities(
                time_range=time_range,
                text_search=text_search,
                metadata_filters=metadata_filters,
                limit=limit
            )
        
    async def process_query(
        self,
        query_text: str,
        time_range: Optional[TimeRange] = None,
        text_search: Optional[str] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        limit: int = 100
    ) -> QueryResult:
        """Process a natural language or structured query about activities.
        
        Args:
            query_text: The user's query text
            time_range: Optional explicit time range to override extraction
            text_search: Optional explicit text search to override extraction
            metadata_filters: Optional explicit metadata filters to apply
            limit: Maximum number of results to return
            
        Returns:
            QueryResult object containing matching activities and metadata
        """
        logger.info(f"ActivityQueryProcessor: Processing query: '{query_text}'")
        start_time = datetime.now()
        
        # Normalize the query text
        normalized_query = self._normalize_query(query_text)
        logger.info(f"Normalized query: '{normalized_query}'")
        
        # Determine the query structure
        structure = self._determine_structure(normalized_query)
        logger.info(f"Query structure determined as: {structure.name}")
        
        # Process according to structure type
        if structure == QueryStructure.STRUCTURED:
            logger.info("Processing as STRUCTURED query")
            results = await self._process_structured_query(
                normalized_query, 
                time_range, 
                metadata_filters,
                limit=limit
            )
        elif structure == QueryStructure.SEMI_STRUCTURED:
            logger.info("Processing as SEMI_STRUCTURED query")
            results = await self._process_semi_structured_query(
                normalized_query,
                time_range,
                metadata_filters,
                limit=limit
            )
        else:  # UNSTRUCTURED
            logger.info("Processing as UNSTRUCTURED query")
            results = await self._process_unstructured_query(
                normalized_query,
                time_range,
                metadata_filters,
                limit=limit
            )
        
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Query processing completed in {duration:.2f} seconds, found {len(results.activities)} activities")
        
        # If text search was explicitly provided, apply it
        if text_search:
            logger.info(f"Applying explicit text search: '{text_search}'")
            results.activities = self._filter_by_keywords(results.activities, text_search)
            
        return results
    
    def _normalize_query(self, query_text: str) -> str:
        """Normalize query text for better matching."""
        return query_text.lower().strip()
    
    def _determine_structure(self, query_text: str) -> QueryStructure:
        """Determine if a query is structured, semi-structured, or unstructured."""
        # First check for known patterns that indicate a structured query
        if self._matches_known_pattern(query_text):
            return QueryStructure.STRUCTURED
        
        # Check for time-based queries, which are common and should be handled as semi-structured
        time_patterns_count = 0
        for pattern_name, pattern in self.time_patterns.items():
            if pattern.search(query_text):
                time_patterns_count += 1
            
        # Time-based queries with clear timeframes should be at least semi-structured
        if time_patterns_count > 0:
            # Check if there are other elements that would make this structured
            action_matches = sum(1 for pattern in self.action_patterns.values() if pattern.search(query_text))
            context_matches = sum(1 for pattern in self.context_patterns.values() if pattern.search(query_text))
            
            # If we have time + (action or context), it's structured
            if action_matches > 0 or context_matches > 0:
                return QueryStructure.STRUCTURED
            # Otherwise, it's at least semi-structured
            return QueryStructure.SEMI_STRUCTURED
        
        # Check for other recognizable elements
        elif self._has_recognizable_elements(query_text):
            return QueryStructure.SEMI_STRUCTURED
        
        # Default to unstructured
        return QueryStructure.UNSTRUCTURED
            
    def _matches_known_pattern(self, query_text: str) -> bool:
        """Check if the query matches a known pattern."""
        for pattern in self.known_patterns:
            if pattern.search(query_text):
                return True
                
        # Check for highly structured queries
        structure_matches = sum(1 for pattern in self.structure_patterns.values() if pattern.search(query_text))
        time_matches = sum(1 for pattern in self.time_patterns.values() if pattern.search(query_text))
        action_matches = sum(1 for pattern in self.action_patterns.values() if pattern.search(query_text))
        context_matches = sum(1 for pattern in self.context_patterns.values() if pattern.search(query_text))
        
        # If query has a clear structure + at least 2 other elements
        total_elements = time_matches + action_matches + context_matches
        return structure_matches >= 1 and total_elements >= 2
    
    def _has_recognizable_elements(self, query_text: str) -> bool:
        """Check if the query has some recognizable elements but isn't fully structured."""
        time_matches = sum(1 for pattern in self.time_patterns.values() if pattern.search(query_text))
        action_matches = sum(1 for pattern in self.action_patterns.values() if pattern.search(query_text))
        context_matches = sum(1 for pattern in self.context_patterns.values() if pattern.search(query_text))
        
        # If query has at least one recognizable element
        return time_matches + action_matches + context_matches > 0
    
    async def _process_unstructured_query(
        self,
        query_text: str,
        time_range: Optional[Dict[str, datetime]] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = 100
    ) -> QueryResult:
        """Process a free-form natural language query."""
        logger.info(f"Processing unstructured query: '{query_text}'")
        
        # For unstructured queries, we'll make a best effort to extract parameters
        
        # Extract time range if not provided
        if not time_range:
            time_range = self._extract_timeframe(query_text)
            logger.info(f"Extracted time range: {time_range}")
            
            # If no time range found, default to recent activities
            if not time_range:
                end_time = datetime.now()
                start_time = end_time - timedelta(days=7)  # Default to last week
                time_range = {'start': start_time, 'end': end_time}
                logger.info(f"Using default time range: {time_range}")
        
        # Extract metadata filters if not provided
        if not metadata_filters:
            context = self._extract_context(query_text)
            metadata_filters = context.get('metadata', {})
            if 'app_name' in context:
                metadata_filters['app_name'] = context['app_name']
            logger.info(f"Extracted metadata filters: {metadata_filters}")
        
        # Use the entire query as text search
        text_search = query_text
        logger.info(f"Using full query as text search: {text_search}")
        
        # Query the knowledge service with proper threading context handling
        activities = await self._search_activities_with_context(
            time_range=time_range,
            text_search=text_search,
            metadata_filters=metadata_filters,
            limit=limit
        )
        
        # Convert to dictionaries for the result
        activity_dicts = [activity.to_dict() for activity in activities]
        
        # Create result with lower confidence for unstructured queries
        return QueryResult(
            activities=activity_dicts,
            confidence=0.5,
            timeframe=time_range,
            inferred_patterns=["unstructured_query"]
        )
    
    def _extract_search_terms(self, query_text: str) -> str:
        """Extract likely search terms from an unstructured query."""
        # Remove common question words and filler words
        stop_words = {"what", "when", "where", "who", "how", "did", "i", "my", "the", "a", "an", "in", "on", "at", "to", "for", "with", "did", "was", "is", "are", "were"}
        
        # Split, filter stop words, and rejoin
        terms = [word for word in query_text.split() if word.lower() not in stop_words]
        return " ".join(terms) if terms else ""
    
    async def _process_semi_structured_query(
        self,
        query_text: str,
        time_range: Optional[Dict[str, datetime]] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        action_type: Optional[str] = None,
        limit: Optional[int] = 100
    ) -> QueryResult:
        """Process a query with some recognizable patterns."""
        logger.info(f"Processing semi-structured query: '{query_text}'")
        
        # Extract time range if not provided
        if not time_range:
            time_range = self._extract_timeframe(query_text)
            logger.info(f"Extracted time range: {time_range}")
        
        # Extract metadata filters if not provided
        if not metadata_filters:
            context = self._extract_context(query_text)
            metadata_filters = context.get('metadata', {})
            if 'app_name' in context:
                metadata_filters['app_name'] = context['app_name']
            logger.info(f"Extracted metadata filters: {metadata_filters}")
        
        # Use the query text itself as the search term
        text_search = query_text
        logger.info(f"Using query text as search term: {text_search}")
        
        # Query the knowledge service with proper threading context handling
        activities = await self._search_activities_with_context(
            time_range=time_range,
            text_search=text_search,
            metadata_filters=metadata_filters,
            limit=limit
        )
        
        # Convert to dictionaries for the result
        activity_dicts = [activity.to_dict() for activity in activities]
        
        # Create result with medium confidence
        return QueryResult(
            activities=activity_dicts,
            confidence=0.7,
            timeframe=time_range,
            inferred_patterns=["semi_structured_query"]
        )
    
    async def _process_structured_query(
        self,
        query_text: str,
        time_range: Optional[Dict[str, datetime]] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        action_type: Optional[str] = None,
        limit: Optional[int] = 100
    ) -> QueryResult:
        """Process a query that matches known patterns."""
        logger.info(f"Processing structured query: '{query_text}'")
        
        # Extract time range if not provided
        if not time_range:
            time_range = self._extract_timeframe(query_text)
            logger.info(f"Extracted time range: {time_range}")
        
        # Extract metadata filters if not provided
        if not metadata_filters:
            context = self._extract_context(query_text)
            metadata_filters = context.get('metadata', {})
            if 'app_name' in context:
                metadata_filters['app_name'] = context['app_name']
            logger.info(f"Extracted metadata filters: {metadata_filters}")
        
        # Extract text search terms - use the query text itself as the search term
        text_search = query_text
        logger.info(f"Using query text as search term: {text_search}")
        
        # Query the knowledge service with proper threading context handling
        activities = await self._search_activities_with_context(
            time_range=time_range,
            text_search=text_search,
            metadata_filters=metadata_filters,
            limit=limit
        )
        
        # Convert to dictionaries for the result
        activity_dicts = [activity.to_dict() for activity in activities]
        
        # Create result with high confidence since this is a structured query
        return QueryResult(
            activities=activity_dicts,
            confidence=0.9,
            timeframe=time_range,
            inferred_patterns=["structured_query"]
        )
    
    def _filter_by_keywords(
        self,
        activities: List[Dict[str, Any]],
        query_text: str
    ) -> List[Dict[str, Any]]:
        """Filter activities by keyword relevance to the query."""
        if not query_text or not activities:
            return activities
            
        # Extract keywords (removing stop words)
        keywords = [word.lower() for word in query_text.split() 
                   if len(word) > 2 and word.lower() not in {
                       "the", "and", "this", "that", "what", "when", "where", 
                       "who", "how", "did", "with", "from", "have", "has", "had"
                   }]
                   
        if not keywords:
            return activities
            
        # Score each activity by keyword matches
        scored_activities = []
        for activity in activities:
            score = 0
            # Create a single string of all textual content
            activity_text = " ".join([
                str(activity.get("title", "")),
                str(activity.get("description", "")),
                str(activity.get("app_name", "")),
                str(activity.get("content_text", "")),
                str(activity.get("window_title", ""))
            ]).lower()
            
            # Count keyword matches
            for keyword in keywords:
                if keyword in activity_text:
                    score += 1
                    
            scored_activities.append((score, activity))
            
        # Sort by score (highest first) and return just the activities
        return [activity for _, activity in sorted(scored_activities, key=lambda x: x[0], reverse=True)]
                
    def _generate_activity_summary(
        self,
        activities: List[Dict[str, Any]],
        query_text: str
    ) -> str:
        """Generate a summary of activities based on the query context."""
        if not activities:
            return "No activities found for this time period or query."
            
        # Group activities by application
        app_groups = {}
        for activity in activities:
            app_name = activity.get("app_name", "Unknown")
            if app_name not in app_groups:
                app_groups[app_name] = []
            app_groups[app_name].append(activity)
            
        # Create summary
        summary_parts = []
        
        # First, a count of activities
        summary_parts.append(f"Found {len(activities)} activities")
        
        # If we have time range information in the activities
        if activities and "start_time" in activities[0]:
            earliest = min(a["start_time"] for a in activities)
            latest = max(a.get("end_time", a["start_time"]) for a in activities)
            time_range = f"from {earliest.strftime('%Y-%m-%d %H:%M')} to {latest.strftime('%Y-%m-%d %H:%M')}"
            summary_parts[0] += f" {time_range}"
        
        # Summary by application
        for app_name, app_activities in sorted(app_groups.items(), key=lambda x: len(x[1]), reverse=True):
            total_duration = sum((a.get("duration_seconds", 0) or 0) for a in app_activities)
            if total_duration > 0:
                duration_str = self._format_duration(total_duration)
                summary_parts.append(f"- {app_name}: {len(app_activities)} activities ({duration_str})")
            else:
                summary_parts.append(f"- {app_name}: {len(app_activities)} activities")
                
        return "\n".join(summary_parts)
        
    def _infer_patterns(
        self,
        query_text: str,
        activities: List[Dict[str, Any]]
    ) -> List[str]:
        """Infer patterns and insights from both the query and results."""
        patterns = []
        
        # From query
        if any(p.search(query_text) for p in self.time_patterns.values()):
            patterns.append("time_based")
            
        if any(p.search(query_text) for p in self.action_patterns.values()):
            patterns.append("action_oriented")
            
        if any(p.search(query_text) for p in self.context_patterns.values()):
            patterns.append("context_specific")
            
        # From results
        if not activities:
            patterns.append("no_results")
            return patterns
            
        # Check for app focus
        app_names = self._find_common_elements(activities, "app_name")
        if len(app_names) == 1:
            patterns.append("single_app_focus")
        elif len(app_names) <= 3:
            patterns.append("few_apps_focus")
        else:
            patterns.append("multi_app_activities")
            
        # Check for duration patterns
        durations = [a.get("duration_seconds", 0) or 0 for a in activities]
        if durations and (sum(durations) / len(durations) > 300):  # Avg > 5 minutes
            patterns.append("long_duration_activities")
        else:
            patterns.append("short_duration_activities")
            
        return patterns
        
    def _find_common_elements(
        self,
        activities: List[Dict[str, Any]],
        field: str
    ) -> Set[str]:
        """Find common elements in a specific field across activities."""
        elements = set()
        for activity in activities:
            if field in activity and activity[field]:
                elements.add(str(activity[field]))
        return elements
        
    def _format_duration(self, seconds: float) -> str:
        """Format a duration in seconds to a human-readable string."""
        if seconds < 60:
            return f"{seconds:.0f} seconds"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f} minutes"
        else:
            hours = seconds / 3600
            return f"{hours:.1f} hours"
    
    def _extract_context(self, query_text: str) -> Dict[str, Any]:
        """Extract context information from a query."""
        context = {}
        
        # Define common words that should not be identified as app names or contexts
        common_words = {
            'the', 'a', 'an', 'this', 'that', 'these', 'those', 'last', 'past', 
            'previous', 'next', 'some', 'any', 'all', 'few', 'many', 'most', 
            'other', 'another', 'such', 'no', 'nor', 'not', 'only', 'then', 
            'so', 'than', 'too', 'very', 'just', 'but', 'yet', 'now', 'today',
            'yesterday', 'tomorrow', 'day', 'week', 'month', 'year', 'time'
        }
        
        # Check for app context
        app_match = self.context_patterns['in_app'].search(query_text)
        if app_match:
            # The second group should contain the app name
            app_name = app_match.group(2).strip()
            
            # Skip common words that might be incorrectly identified as app names
            if app_name.lower() not in common_words and len(app_name) > 2:
                # Check if this is part of a time-based query
                time_related = any(pattern.search(app_name) for pattern in self.time_patterns.values())
                if not time_related:
                    context['app_name'] = app_name
        
        # Check for project context
        project_match = self.context_patterns['project'].search(query_text)
        if project_match:
            # The second group should contain the project name
            project = project_match.group(2).strip()
            if project.lower() not in common_words and len(project) > 2:
                if 'metadata' not in context:
                    context['metadata'] = {}
                context['metadata']['project'] = project
        
        # Try to extract topic/keyword context
        topic_match = self.context_patterns['topic'].search(query_text)
        if topic_match:
            # The second group should contain the topic
            topic = topic_match.group(2).strip()
            if topic.lower() not in common_words and len(topic) > 2:
                # Check if this is part of a time-based query
                time_related = any(pattern.search(topic) for pattern in self.time_patterns.values())
                if not time_related:
                    if 'metadata' not in context:
                        context['metadata'] = {}
                    context['metadata']['topic'] = topic
                
        return context
    
    def _extract_action(self, query_text: str) -> str:
        """Extract the primary action from the query."""
        for action_type, pattern in self.action_patterns.items():
            if pattern.search(query_text):
                return action_type
        return ""
    
    def _extract_timeframe(self, query_text: str) -> Optional[Dict[str, datetime]]:
        """Extract timeframe information from a query."""
        print(f"\n==== EXTRACTING TIMEFRAME FROM: '{query_text}' ====")
        now = datetime.now()  # Changed from datetime.utcnow() to match actual storage timezone (local)
        print(f"Current time (Local): {now}")
        
        # Check for "today"
        if self.time_patterns['today'].search(query_text):
            print("Matched 'today' pattern")
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = now
            print(f"Start time: {start_time}")
            print(f"End time: {end_time}")
            print(f"Start time ISO: {start_time.isoformat()}")
            print(f"End time ISO: {end_time.isoformat()}")
            return {"start": start_time, "end": end_time}
            
        # Check for "yesterday"
        if self.time_patterns['yesterday'].search(query_text):
            print("Matched 'yesterday' pattern")
            yesterday = now - timedelta(days=1)
            start_time = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
            print(f"Start time: {start_time}")
            print(f"End time: {end_time}")
            print(f"Start time ISO: {start_time.isoformat()}")
            print(f"End time ISO: {end_time.isoformat()}")
            return {"start": start_time, "end": end_time}
            
        # Check for "this week"
        if self.time_patterns['this_week'].search(query_text):
            print("Matched 'this week' pattern")
            # Assuming weeks start on Monday
            days_since_monday = now.weekday()
            start_of_week = now - timedelta(days=days_since_monday)
            start_time = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
            print(f"Start time: {start_time}")
            print(f"End time: {now}")
            print(f"Start time ISO: {start_time.isoformat()}")
            print(f"End time ISO: {now.isoformat()}")
            return {"start": start_time, "end": now}
            
        # Check for "last week"
        if self.time_patterns['last_week'].search(query_text):
            print("Matched 'last week' pattern")
            # Last week
            days_since_monday = now.weekday()
            start_of_this_week = now - timedelta(days=days_since_monday)
            end_of_last_week = start_of_this_week - timedelta(microseconds=1)
            start_of_last_week = end_of_last_week - timedelta(days=6)
            start_time = start_of_last_week.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = end_of_last_week
            print(f"Start time: {start_time}")
            print(f"End time: {end_time}")
            print(f"Start time ISO: {start_time.isoformat()}")
            print(f"End time ISO: {end_time.isoformat()}")
            return {"start": start_time, "end": end_time}
            
        # Check for "this month"
        if self.time_patterns['this_month'].search(query_text):
            print("Matched 'this month' pattern")
            start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # For "this month", include the entire current day by setting end time to end of today
            end_time = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            print(f"Start time: {start_time}")
            print(f"End time: {end_time}")
            print(f"Start time ISO: {start_time.isoformat()}")
            print(f"End time ISO: {end_time.isoformat()}")
            return {"start": start_time, "end": end_time}
            
        # Check for "last month"
        if self.time_patterns['last_month'].search(query_text):
            print("Matched 'last month' pattern")
            if now.month == 1:
                last_month = now.replace(year=now.year-1, month=12, day=1)
            else:
                last_month = now.replace(month=now.month-1, day=1)
            
            start_time = last_month
            if now.month == 1:
                end_time = now.replace(year=now.year-1, month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)
            else:
                end_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(microseconds=1)
            
            print(f"Start time: {start_time}")
            print(f"End time: {end_time}")
            print(f"Start time ISO: {start_time.isoformat()}")
            print(f"End time ISO: {end_time.isoformat()}")
            return {"start": start_time, "end": end_time}
            
        # Check for "last N days/weeks/months"
        n_days_match = self.time_patterns['n_days'].search(query_text)
        if n_days_match:
            print("Matched 'last N days/weeks/months' pattern")
            number = int(n_days_match.group(2))
            unit = n_days_match.group(3).lower()
            print(f"Number: {number}, Unit: {unit}")
            
            if unit.startswith('day'):
                start_time = now - timedelta(days=number)
            elif unit.startswith('week'):
                start_time = now - timedelta(days=number*7)
            elif unit.startswith('month'):
                # Approximate a month as 30 days
                start_time = now - timedelta(days=number*30)
            else:
                print("Unknown time unit")
                return None
                
            print(f"Start time: {start_time}")
            print(f"End time: {now}")
            print(f"Start time ISO: {start_time.isoformat()}")
            print(f"End time ISO: {now.isoformat()}")
            return {"start": start_time, "end": now}
            
        # For more complex date parsing, a dedicated library like dateparser would be better
        print("No time pattern matched")
        print("==== END EXTRACTING TIMEFRAME ====\n")
        return None
    
    def _generate_summary(
        self,
        activities: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> str:
        """Generate a summary of activities based on context."""
        if not activities:
            return "No activities found matching your query."
            
        app_name = context.get("app_name")
        topic = context.get("topic")
        project = context.get("project")
        
        summary_parts = []
        
        # If we have app context
        if app_name:
            app_activities = [a for a in activities if a.get("app_name", "").lower() == app_name.lower()]
            if app_activities:
                total_time = sum((a.get("duration_seconds", 0) or 0) for a in app_activities)
                time_str = self._format_duration(total_time)
                summary_parts.append(f"Used {app_name} for {time_str} across {len(app_activities)} sessions.")
                
        # If we have project context
        elif project:
            summary_parts.append(f"Found {len(activities)} activities related to project '{project}'.")
            
        # If we have topic context
        elif topic:
            summary_parts.append(f"Found {len(activities)} activities related to '{topic}'.")
            
        # Generic summary if no specific context
        else:
            summary_parts.append(f"Found {len(activities)} activities in total.")
            
        # Add time range information
        if activities and "start_time" in activities[0]:
            earliest = min(a["start_time"] for a in activities)
            latest = max(a.get("end_time", a["start_time"]) for a in activities)
            summary_parts.append(f"Time range: {earliest.strftime('%Y-%m-%d %H:%M')} to {latest.strftime('%Y-%m-%d %H:%M')}")
            
        return " ".join(summary_parts)
    
    def _generate_analysis(
        self,
        activities: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> str:
        """Generate an analysis of the activities."""
        if not activities:
            return ""
            
        analysis = []
        
        # Group by app
        apps = {}
        for activity in activities:
            app = activity.get("app_name", "Unknown")
            if app not in apps:
                apps[app] = []
            apps[app].append(activity)
            
        # Top apps by time
        top_apps = []
        for app, app_activities in apps.items():
            total_time = sum((a.get("duration_seconds", 0) or 0) for a in app_activities)
            if total_time > 0:
                top_apps.append((app, total_time, len(app_activities)))
                
        top_apps.sort(key=lambda x: x[1], reverse=True)
        
        # Most used applications
        if top_apps:
            analysis.append("Top applications by time spent:")
            for i, (app, time, count) in enumerate(top_apps[:3], 1):
                time_str = self._format_duration(time)
                analysis.append(f"{i}. {app}: {time_str} across {count} sessions")
                
        # Time of day analysis
        morning = sum(1 for a in activities if a.get("start_time") and a["start_time"].hour < 12)
        afternoon = sum(1 for a in activities if a.get("start_time") and 12 <= a["start_time"].hour < 17)
        evening = sum(1 for a in activities if a.get("start_time") and 17 <= a["start_time"].hour < 21)
        night = sum(1 for a in activities if a.get("start_time") and a["start_time"].hour >= 21)
        
        analysis.append("\nActivity distribution by time of day:")
        analysis.append(f"- Morning (before 12pm): {morning} activities")
        analysis.append(f"- Afternoon (12pm-5pm): {afternoon} activities")
        analysis.append(f"- Evening (5pm-9pm): {evening} activities")
        analysis.append(f"- Night (after 9pm): {night} activities")
        
        return "\n".join(analysis)
    
    def _extract_query_components(self, query_text: str) -> Dict[str, Any]:
        """Extract all structured components from a query."""
        components = {}
        
        # Extract timeframe
        timeframe = self._extract_timeframe(query_text)
        if timeframe:
            components["timeframe"] = timeframe
            
        # Extract context
        context = self._extract_context(query_text)
        if context:
            components["context"] = context
            
        # Extract action
        action = self._extract_action(query_text)
        if action:
            components["action"] = action
            
        # Extract patterns
        patterns = []
        for struct_type, pattern in self.structure_patterns.items():
            if pattern.search(query_text):
                patterns.append(struct_type)
        if patterns:
            components["patterns"] = patterns
            
        return components
    
    def _generate_structured_response(
        self,
        activities: List[Dict[str, Any]],
        components: Dict[str, Any]
    ) -> str:
        """Generate a structured response based on query components."""
        if not activities:
            return "No activities found matching your query."
            
        # Get structured patterns to determine response format
        patterns = components.get("patterns", [])
        
        # If it's a summary query
        if "summary_query" in patterns:
            return self._generate_summary(activities, components.get("context", {}))
            
        # If it's a count query
        if "count_query" in patterns:
            count = len(activities)
            context = components.get("context", {})
            app = context.get("app_name", "")
            project = context.get("project", "")
            
            if app:
                return f"Found {count} activities using {app}."
            elif project:
                return f"Found {count} activities related to project {project}."
            else:
                return f"Found {count} activities matching your query."
                
        # If it's a time query
        if "time_query" in patterns:
            total_time = sum((a.get("duration_seconds", 0) or 0) for a in activities)
            time_str = self._format_duration(total_time)
            
            context = components.get("context", {})
            app = context.get("app_name", "")
            project = context.get("project", "")
            
            if app:
                return f"Spent {time_str} using {app}."
            elif project:
                return f"Spent {time_str} on project {project}."
            else:
                return f"Spent {time_str} on matching activities."
        
        # Default to standard summary and analysis
        summary = self._generate_summary(activities, components.get("context", {}))
        analysis = self._generate_analysis(activities, components.get("context", {}))
        
        return f"{summary}\n\n{analysis}" 