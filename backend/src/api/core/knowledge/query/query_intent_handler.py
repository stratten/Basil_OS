"""Process queries using LLM for interpretation."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set
import json
import logging
import time
import re

from ...llm import LLMService
from ...models.model_invocation import call_model_with_prompt
from ...models.model_types import ModelCapability
from .activity_query_processor import QueryResult
from ...models.preferences import Preferences
from ....services.model_usage_service import ModelUsageService

logger = logging.getLogger(__name__)

@dataclass
class QueryContext:
    """Track conversation context to help LLM interpret queries more accurately.
    
    This context helps the model understand:
    - Previous queries and their results
    - Active filters or focus areas
    - Time ranges being discussed
    - Common patterns in user's queries
    """
    # Temporal context
    last_query_time: Optional[datetime] = None
    assumed_timeframe: Optional[Dict[str, datetime]] = None
    referenced_times: List[datetime] = field(default_factory=list)
    
    # Query history
    last_queries: List[str] = field(default_factory=list)
    last_results: List[Dict[str, Any]] = field(default_factory=list)
    max_history: int = 5  # Keep last N queries for context
    
    # Active filters
    active_filters: Dict[str, Any] = field(default_factory=dict)
    focused_apps: Set[str] = field(default_factory=set)
    focused_projects: Set[str] = field(default_factory=set)
    
    # User patterns
    common_apps: Dict[str, int] = field(default_factory=dict)  # app -> frequency
    query_patterns: Dict[str, int] = field(default_factory=dict)  # pattern -> frequency
    
    def update_with_query(self, query_text: str, results: Optional[Dict[str, Any]] = None) -> None:
        """Update context with new query information."""
        # Simple implementation for now
        self.last_query_time = datetime.now()
        self.last_queries.append(query_text)
        if results:
            self.last_results.append(results)


class QueryIntentHandler:
    """Handles the interpretation of user queries using LLM."""
    
    def __init__(
        self, 
        query_processor,
        image_processor=None,
        llm_service: Optional[LLMService] = None,
        model_service=None,
        model_usage_service: Optional[ModelUsageService] = None,
    ) -> None:
        """Initialize the query intent handler.
        
        Args:
            query_processor: The processor that will execute the interpreted query
            image_processor: Optional service for processing images
            llm_service: Optional service for LLM-based query interpretation (deprecated)
            model_service: Optional model service for direct access to AI models
            model_usage_service: Optional service for model selection and initialization
        """
        self.query_processor = query_processor
        self.image_processor = image_processor
        self.llm_service = llm_service  # Keep for backward compatibility
        self.model_service = model_service  # Store model_service
        self.model_usage_service = model_usage_service  # Store model_usage_service
        self.context = QueryContext()
        self.active_model = None  # Track the currently loaded model
    
    async def process_query(self, query_text: str, model_id: Optional[str] = None) -> Dict[str, Any]:
        """Process a user query using LLM interpretation as the primary method.
        
        Args:
            query_text: The text of the user's query
            model_id: Optional specific model to use for processing
            
        Returns:
            A dictionary containing the results and metadata
        """
        logger.info(f"=== PROCESSING QUERY: '{query_text}' ===")
        result = None
        
        # Always attempt LLM-based interpretation first if we have model services
        if self.model_usage_service:
            logger.info("Using LLM-based query interpretation as primary method")
            try:
                # Get model for reasoning task, using model_id if specified
                model = await self.model_usage_service.get_model_for_task(
                    capabilities={ModelCapability.REASONING},
                    explicit_model_id=model_id,
                )
                
                if model:
                    self.active_model = model
                    logger.info(f"Using model: {getattr(model, 'model_name', 'unknown')} for query processing")
                    
                    # Step 1: Analyze the query to determine intent
                    logger.info("Step 1: Analyzing query intent")
                    logger.info("🔍 [DEBUG] Calling model.generate_response for intent analysis…")
                    intent_prompt = f"Analyze this query and determine what information the user is looking for: '{query_text}'"
                    intent_response = await call_model_with_prompt(
                        model,
                        prompt=intent_prompt,
                        max_tokens=200,
                        enable_web_search=False,
                    )
                    logger.info(f"🔍 [DEBUG] Intent analysis returned: {intent_response!r}")
                    logger.info(f"Intent analysis: {intent_response}")
                    
                    # Step 2: Generate query parameters based on intent
                    logger.info("Step 2: Generating SQL query")
                    logger.info("🗄️ [DEBUG] Calling model.generate_response for SQL generation…")
                    
                    # Get the activities table schema
                    # Check if we're in ThreadPoolExecutor context and use sync method
                    import threading
                    current_thread = threading.current_thread()
                    if (current_thread.name.startswith('ThreadPoolExecutor') or 
                        'run_agent_task_in_thread' in current_thread.name):
                        # Use synchronous version to avoid event loop conflicts
                        schema_info = self.query_processor.knowledge_service.get_schema_info_sync()
                    else:
                        # Use async version in normal context
                        schema_info = await self.query_processor.knowledge_service.get_schema_info()
                    logger.info(f"Retrieved database schema with {len(schema_info['tables'])} tables")
                    
                    # Format the activities table schema for the prompt
                    schema_description = "Activities Table Schema:\n"
                    if 'activities' in schema_info["tables"]:
                        schema_description += "  Columns:\n"
                        for column in schema_info["tables"]["activities"]["columns"]:
                            pk_indicator = " (Primary Key)" if column["pk"] else ""
                            schema_description += f"    - {column['name']}: {column['type']}{pk_indicator}\n"
                    
                    # Add activity_metadata table schema
                    if 'activity_metadata' in schema_info["tables"]:
                        schema_description += "\nActivity Metadata Table Schema:\n"
                        schema_description += "  Columns:\n"
                        for column in schema_info["tables"]["activity_metadata"]["columns"]:
                            pk_indicator = " (Primary Key)" if column["pk"] else ""
                            schema_description += f"    - {column['name']}: {column['type']}{pk_indicator}\n"
                    
                    # Add relationship information for activities
                    if schema_info["relationships"]:
                        schema_description += "\nRelationships:\n"
                        for rel in schema_info["relationships"]:
                            if rel['table'] == 'activities' or rel['ref_table'] == 'activities':
                                schema_description += f"  - {rel['table']}.{rel['column']} -> {rel['ref_table']}.{rel['ref_column']}\n"
                    
                    # Calculate current date ranges for the prompt
                    today = datetime.now()
                    yesterday_start = (today - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                    yesterday_end = (today - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)
                    today_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
                    today_end = today.replace(hour=23, minute=59, second=59, microsecond=999999)
                    
                    # Enhanced SQL generation prompt with better time handling
                    sql_prompt = f"""Based on the query '{query_text}', generate a SQLite-compatible SQL query to search the activities table.

{schema_description}

IMPORTANT GUIDELINES:
1. Use ONLY SQLite syntax - do NOT use SQL Server, MySQL, or other database-specific features
2. Use direct ISO format date strings with the CURRENT DATE, not hardcoded dates
3. Always use proper time ranges (start AND end timestamps) for time-based queries
4. Handle natural language time expressions properly:
   - "today" = '{today_start.isoformat()}' to '{today_end.isoformat()}'
   - "yesterday" = '{yesterday_start.isoformat()}' to '{yesterday_end.isoformat()}'
   - "past two days" = '{(today - timedelta(days=2)).isoformat()}' to '{today.isoformat()}'
   - "last N days" = calculate from today backwards
   - Written numbers like "two", "three" should be treated as 2, 3, etc.

Time-based query examples:

1. For "today" queries:
```sql
SELECT a.id, a.timestamp, a.app_name, a.window_title, a.extracted_text, a.duration
FROM activities a
WHERE a.timestamp >= '{today_start.isoformat()}' AND a.timestamp <= '{today_end.isoformat()}'
ORDER BY a.timestamp DESC
LIMIT 100
```

2. For "yesterday" queries:
```sql
SELECT a.id, a.timestamp, a.app_name, a.window_title, a.extracted_text, a.duration
FROM activities a
WHERE a.timestamp >= '{yesterday_start.isoformat()}' AND a.timestamp <= '{yesterday_end.isoformat()}'
ORDER BY a.timestamp DESC
LIMIT 100
```

3. For "past two days" or "last two days" queries:
```sql
SELECT a.id, a.timestamp, a.app_name, a.window_title, a.extracted_text, a.duration
FROM activities a
WHERE a.timestamp >= '{(datetime.now() - timedelta(days=2)).isoformat()}' AND a.timestamp <= '{datetime.now().isoformat()}'
ORDER BY a.timestamp DESC
LIMIT 100
```

The query should:
1. Select relevant columns from the activities table
2. Include appropriate WHERE clauses with proper time ranges
3. Order results by timestamp in descending order
4. Limit the results to a reasonable number (e.g., 100)

For your query '{query_text}', generate the appropriate SQLite-compatible SQL query:
"""
                    sql_response = await call_model_with_prompt(
                        model,
                        prompt=sql_prompt,
                        max_tokens=500,
                        enable_web_search=False,
                    )
                    logger.info(f"🗄️ [DEBUG] SQL generation returned: {sql_response!r}")
                    logger.info(f"Generated SQL query: {sql_response}")
                    
                    # Extract and process the SQL query
                    try:
                        # Extract SQL if it's embedded in markdown code blocks
                        sql_query = sql_response
                        if "```sql" in sql_response:
                            sql_start = sql_response.find("```sql") + 6
                            sql_end = sql_response.find("```", sql_start)
                            if sql_end > sql_start:
                                sql_query = sql_response[sql_start:sql_end].strip()
                        elif "```" in sql_response:
                            sql_start = sql_response.find("```") + 3
                            sql_end = sql_response.find("```", sql_start)
                            if sql_end > sql_start:
                                sql_query = sql_response[sql_start:sql_end].strip()
                        
                        logger.info(f"Extracted SQL query: {sql_query}")
                        
                        # Post-process the SQL query to ensure dates are current
                        sql_query = self._post_process_sql_query(sql_query, query_text)
                        logger.info(f"Post-processed SQL query: {sql_query}")
                        
                        # Parse the SQL query to extract parameters for search_activities
                        time_range = None
                        text_search = None
                        metadata_filters = None
                        limit = 100
                        
                        # Extract time range from SQL
                        start_time_match = re.search(r"timestamp\s*>=\s*'([^']+)'", sql_query)
                        end_time_match = re.search(r"timestamp\s*<=\s*'([^']+)'", sql_query)
                        
                        if start_time_match and end_time_match:
                            try:
                                time_range = {
                                    "start": datetime.fromisoformat(start_time_match.group(1)),
                                    "end": datetime.fromisoformat(end_time_match.group(1))
                                }
                                logger.info(f"Extracted time range from SQL: {time_range}")
                            except ValueError as e:
                                logger.warning(f"Could not parse extracted dates: {e}")
                        
                        # Extract text search from SQL (look for MATCH or LIKE clauses)
                        text_match = re.search(r"content\s+MATCH\s+'([^']+)'", sql_query, re.IGNORECASE)
                        like_match = re.search(r"(extracted_text|window_title)\s+LIKE\s+'%([^%]+)%'", sql_query, re.IGNORECASE)
                        
                        if text_match:
                            text_search = text_match.group(1)
                        elif like_match:
                            text_search = like_match.group(2)
                        
                        # Extract limit from SQL
                        limit_match = re.search(r"LIMIT\s+(\d+)", sql_query, re.IGNORECASE)
                        if limit_match:
                            limit = int(limit_match.group(1))
                        
                        # Extract metadata filters from SQL (look for JOIN with activity_metadata)
                        if "activity_metadata" in sql_query:
                            metadata_filters = {}
                            meta_matches = re.finditer(r"m_\w+\.key\s*=\s*'([^']+)'\s+AND\s+m_\w+\.value\s*=\s*'([^']+)'", sql_query, re.IGNORECASE)
                            
                            for match in meta_matches:
                                key = match.group(1)
                                value = match.group(2)
                                # Validate filters against the original query
                                if value.lower() in query_text.lower():
                                    metadata_filters[key] = value
                                    logger.info(f"Added metadata filter: {key}={value}")
                            
                            if not metadata_filters:
                                metadata_filters = None
                        
                        logger.info(f"Extracted parameters: time_range={time_range}, text_search={text_search}, metadata_filters={metadata_filters}, limit={limit}")
                        
                        # Execute the query with the extracted parameters
                        result = await self.query_processor.process_query(
                            query_text=query_text,
                            time_range=time_range,
                            text_search=text_search,
                            metadata_filters=metadata_filters,
                            limit=limit
                        )
                        logger.info(f"Query processing result: {result.to_dict() if result else None}")
                        
                        # If no results were found and we had metadata filters, try again without them
                        if result and not result.activities and metadata_filters:
                            logger.info("No results found with metadata filters. Retrying without filters.")
                            retry_result = await self.query_processor.process_query(
                                query_text=query_text,
                                time_range=time_range,
                                text_search=text_search,
                                metadata_filters=None,
                                limit=limit
                            )
                            
                            if retry_result and retry_result.activities:
                                logger.info(f"Retry successful! Found {len(retry_result.activities)} activities without metadata filters.")
                                result = retry_result
                        
                    except Exception as e:
                        logger.error(f"Error parsing SQL query: {e}")
                        # If SQL parsing fails, return an error rather than falling back
                        return {
                            "query": query_text,
                            "error": f"Failed to parse LLM-generated SQL query: {str(e)}",
                            "activities": [],
                            "confidence": 0.0,
                            "timeframe": None,
                            "model_id": model.name
                        }
                else:
                    logger.warning("No suitable model found by model_usage_service")
                    # Return an error rather than falling back to regex patterns
                    return {
                        "query": query_text,
                        "error": "No suitable LLM model available for query processing",
                        "activities": [],
                        "confidence": 0.0,
                        "timeframe": None,
                        "model_id": None
                    }
            
            except Exception as e:
                logger.error(f"Error using model for query processing: {e}")
                # Return an error rather than falling back to regex patterns
                return {
                    "query": query_text,
                    "error": f"LLM query processing failed: {str(e)}",
                    "activities": [],
                    "confidence": 0.0,
                    "timeframe": None,
                    "model_id": getattr(self.active_model, "model_name", None)
                }
        else:
            logger.warning("No model usage service available for LLM-based query processing")
            # Return an error rather than falling back to regex patterns
            return {
                "query": query_text,
                "error": "LLM-based query processing not available - no model usage service",
                "activities": [],
                "confidence": 0.0,
                "timeframe": None,
                "model_id": None
            }
        
        # Update context
        self.context.update_with_query(query_text, result.to_dict() if result else None)
        
        # Return successful results
        response = {
            "query": query_text,
            "raw_results": result,
            "result_type": "activity_query",
            "activities": result.activities,
            "confidence": result.confidence,
            "timeframe": result.timeframe,
            "model_id": getattr(self.active_model, "model_name", None)
        }
        
        logger.info(f"=== QUERY PROCESSING COMPLETE ===")
        logger.info(f"Found {len(result.activities)} activities with confidence {result.confidence}")
        
        return response

    async def generate_suggestions(self, input_text: str) -> Dict[str, Any]:
        """Generate suggestions based on input text.
        
        This is a stub implementation to support the hotkey router.
        
        Args:
            input_text: The input text to generate suggestions from
            
        Returns:
            A dictionary containing the suggestions
        """
        logger.info(f"Generating suggestions for: {input_text}")
        return {
            "suggestions": ["This is a placeholder suggestion."],
            "confidence": 0.5
        }

    def _post_process_sql_query(self, sql_query: str, query_text: str) -> str:
        """Post-process the generated SQL query to ensure dates are current.
        
        Args:
            sql_query: The SQL query generated by the model
            query_text: The original user query
            
        Returns:
            The post-processed SQL query
        """
        logger.info(f"Post-processing SQL query: {sql_query}")
        logger.info(f"Original query text: {query_text}")
        
        # Check if this is a time-based query
        today_keywords = ["today", "this day", "current day"]
        yesterday_keywords = ["yesterday"]
        last_n_days_pattern = re.compile(r'(in the last|last|past|previous)\s+(\d+)\s+(days?|weeks?|months?)', re.IGNORECASE)
        between_dates_pattern = re.compile(r'between\s+([\w\s,]+)\s+and\s+([\w\s,]+)', re.IGNORECASE)
        since_date_pattern = re.compile(r'since\s+([\w\s,]+)', re.IGNORECASE)
        
        # Get current date ranges
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_end = (now - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Check for date patterns in the SQL query
        start_date_pattern = r"timestamp\s*>=\s*'([^']+)'"
        end_date_pattern = r"timestamp\s*<=\s*'([^']+)'"
        
        # Check for variable-based date patterns (e.g., @start_date)
        variable_date_pattern = r"timestamp\s*>=\s*@([a-zA-Z0-9_]+)"
        
        # Check for DATEADD functions
        dateadd_pattern = re.compile(r"DATEADD\s*\(\s*(\w+)\s*,\s*(-?\d+)\s*,\s*GETDATE\(\)\s*\)", re.IGNORECASE)
        dateadd_matches = dateadd_pattern.findall(sql_query)
        
        # Replace DATEADD functions with actual dates
        if dateadd_matches:
            logger.info(f"Found DATEADD functions in SQL query: {dateadd_matches}")
            
            for unit, value in dateadd_matches:
                days = 0
                value = int(value)
                
                # Convert the unit to days
                if unit.lower() == 'day':
                    days = value
                elif unit.lower() == 'week':
                    days = value * 7
                elif unit.lower() == 'month':
                    days = value * 30
                elif unit.lower() == 'year':
                    days = value * 365
                
                # Calculate the date
                date = (now + timedelta(days=days)).strftime('%Y-%m-%d')
                
                # Replace the DATEADD function with the actual date
                sql_query = sql_query.replace(f"DATEADD({unit}, {value}, GETDATE())", f"'{date}'")
        
        # Check if query is about today
        if any(keyword in query_text.lower() for keyword in today_keywords):
            logger.info("Detected 'today' query, ensuring correct date range")
            
            # Replace start date
            sql_query = re.sub(
                start_date_pattern,
                f"timestamp >= '{today_start.isoformat()}'",
                sql_query
            )
            
            # Replace end date
            sql_query = re.sub(
                end_date_pattern,
                f"timestamp <= '{today_end.isoformat()}'",
                sql_query
            )
            
        # Check if query is about yesterday
        elif any(keyword in query_text.lower() for keyword in yesterday_keywords):
            logger.info("Detected 'yesterday' query, ensuring correct date range")
            
            # Replace start date
            sql_query = re.sub(
                start_date_pattern,
                f"timestamp >= '{yesterday_start.isoformat()}'",
                sql_query
            )
            
            # Replace end date
            sql_query = re.sub(
                end_date_pattern,
                f"timestamp <= '{yesterday_end.isoformat()}'",
                sql_query
            )
        
        # Check if query is about last N days
        elif last_n_days_match := last_n_days_pattern.search(query_text.lower()):
            logger.info("Detected 'last N days' query, ensuring correct date range")
            
            # Extract the number and unit
            number = int(last_n_days_match.group(2))
            unit = last_n_days_match.group(3).lower()
            
            # Calculate the start date
            if unit.startswith('day'):
                start_time = now - timedelta(days=number)
            elif unit.startswith('week'):
                start_time = now - timedelta(days=number*7)
            elif unit.startswith('month'):
                # Approximate a month as 30 days
                start_time = now - timedelta(days=number*30)
            else:
                # Default to days if unit is not recognized
                start_time = now - timedelta(days=number)
            
            # Format the dates for SQL
            start_date = start_time.strftime('%Y-%m-%d')
            end_date = now.strftime('%Y-%m-%d')
            
            logger.info(f"Calculated date range: {start_date} to {end_date}")
            
            # Check if the SQL uses a variable for the start date
            variable_match = re.search(variable_date_pattern, sql_query)
            if variable_match:
                # Replace the variable declaration and usage with direct date
                var_name = variable_match.group(1)
                # Remove the SET statement
                sql_query = re.sub(r"SET\s+@" + var_name + r"\s*=\s*[^;]+;", "", sql_query)
                # Replace the variable usage
                sql_query = re.sub(
                    r"timestamp\s*>=\s*@" + var_name,
                    f"timestamp >= '{start_date}'",
                    sql_query
                )
            else:
                # Check if there's already a date condition in the SQL query
                date_condition_exists = re.search(r"timestamp\s*>=\s*'[^']+'\s*AND\s*timestamp\s*<=\s*'[^']+'", sql_query)
                
                if date_condition_exists:
                    # Replace the existing date condition
                    sql_query = re.sub(
                        r"timestamp\s*>=\s*'[^']+'\s*AND\s*timestamp\s*<=\s*'[^']+'",
                        f"timestamp >= '{start_date}' AND timestamp <= '{end_date}'",
                        sql_query
                    )
                else:
                    # Replace any existing start date
                    start_date_exists = re.search(start_date_pattern, sql_query)
                    if start_date_exists:
                        sql_query = re.sub(
                            start_date_pattern,
                            f"timestamp >= '{start_date}'",
                            sql_query
                        )
                    
                    # Replace any existing end date
                    end_date_exists = re.search(end_date_pattern, sql_query)
                    if end_date_exists:
                        sql_query = re.sub(
                            end_date_pattern,
                            f"timestamp <= '{end_date}'",
                            sql_query
                        )
                    
                    # If no date conditions exist, add them
                    if not start_date_exists and not end_date_exists:
                        # Find the WHERE clause
                        where_match = re.search(r"WHERE\s+", sql_query, re.IGNORECASE)
                        if where_match:
                            # Add the date conditions after WHERE
                            where_pos = where_match.end()
                            sql_query = (
                                sql_query[:where_pos] + 
                                f"timestamp >= '{start_date}' AND timestamp <= '{end_date}' AND " + 
                                sql_query[where_pos:]
                            )
                        else:
                            # Add a WHERE clause before ORDER BY
                            order_match = re.search(r"ORDER\s+BY", sql_query, re.IGNORECASE)
                            if order_match:
                                order_pos = order_match.start()
                                sql_query = (
                                    sql_query[:order_pos] + 
                                    f"WHERE timestamp >= '{start_date}' AND timestamp <= '{end_date}' " + 
                                    sql_query[order_pos:]
                                )
                            else:
                                # Add a WHERE clause at the end of the query
                                from_match = re.search(r"FROM\s+activities", sql_query, re.IGNORECASE)
                                if from_match:
                                    from_pos = from_match.end()
                                    sql_query = (
                                        sql_query[:from_pos] + 
                                        f" WHERE timestamp >= '{start_date}' AND timestamp <= '{end_date}'" + 
                                        sql_query[from_pos:]
                                    )
        
        # Check if query is about between two dates
        elif between_match := between_dates_pattern.search(query_text.lower()):
            logger.info("Detected 'between dates' query, ensuring correct date range")
            
            # Extract the dates
            start_date_str = between_match.group(1).strip()
            end_date_str = between_match.group(2).strip()
            
            logger.info(f"Extracted date range strings: start='{start_date_str}', end='{end_date_str}'")
            
            # Try to parse the dates
            try:
                # Try different date formats - add more formats to handle various user inputs
                date_formats = [
                    '%B %d',          # February 14
                    '%B %dst',        # February 14st
                    '%B %dnd',        # February 22nd
                    '%B %drd',        # February 23rd
                    '%B %dth',        # February 14th
                    '%b %d',          # Feb 14
                    '%b %dst',        # Feb 14st
                    '%b %dnd',        # Feb 22nd
                    '%b %drd',        # Feb 23rd
                    '%b %dth',        # Feb 14th
                    '%B %d, %Y',      # February 14, 2023
                    '%B %dst, %Y',    # February 14st, 2023
                    '%B %dnd, %Y',    # February 22nd, 2023
                    '%B %drd, %Y',    # February 23rd, 2023
                    '%B %dth, %Y',    # February 14th, 2023
                    '%b %d, %Y',      # Feb 14, 2023
                    '%b %dst, %Y',    # Feb 14st, 2023
                    '%b %dnd, %Y',    # Feb 22nd, 2023
                    '%b %drd, %Y',    # Feb 23rd, 2023
                    '%b %dth, %Y',    # Feb 14th, 2023
                    '%Y-%m-%d',       # 2023-02-14
                    '%m/%d/%Y',       # 02/14/2023
                    '%d/%m/%Y',       # 14/02/2023
                ]
                
                parsed_start_date = None
                parsed_end_date = None
                
                # First, try to clean up the date strings by removing ordinal suffixes
                clean_start_date_str = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', start_date_str)
                clean_end_date_str = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', end_date_str)
                
                logger.info(f"Cleaned date strings: start='{clean_start_date_str}', end='{clean_end_date_str}'")
                
                # Try parsing with the cleaned strings first
                for date_format in ['%B %d', '%b %d', '%B %d, %Y', '%b %d, %Y', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y']:
                    try:
                        # For formats without year, add the current year
                        if '%Y' not in date_format:
                            parsed_start_date = datetime.strptime(f"{clean_start_date_str} {now.year}", f"{date_format} %Y")
                            parsed_end_date = datetime.strptime(f"{clean_end_date_str} {now.year}", f"{date_format} %Y")
                        else:
                            parsed_start_date = datetime.strptime(clean_start_date_str, date_format)
                            parsed_end_date = datetime.strptime(clean_end_date_str, date_format)
                        
                        logger.info(f"Successfully parsed with format {date_format}")
                        break
                    except ValueError:
                        continue
                
                # If that didn't work, try with the original strings and all formats
                if not parsed_start_date or not parsed_end_date:
                    for date_format in date_formats:
                        try:
                            # For formats without year, add the current year
                            if '%Y' not in date_format:
                                parsed_start_date = datetime.strptime(f"{start_date_str} {now.year}", f"{date_format} %Y")
                                parsed_end_date = datetime.strptime(f"{end_date_str} {now.year}", f"{date_format} %Y")
                            else:
                                parsed_start_date = datetime.strptime(start_date_str, date_format)
                                parsed_end_date = datetime.strptime(end_date_str, date_format)
                            
                            logger.info(f"Successfully parsed with format {date_format}")
                            break
                        except ValueError:
                            continue
                
                # If we successfully parsed the dates
                if parsed_start_date and parsed_end_date:
                    start_date = parsed_start_date.strftime('%Y-%m-%d')
                    end_date = parsed_end_date.strftime('%Y-%m-%d')
                    
                    logger.info(f"Successfully parsed date range: {start_date} to {end_date}")
                    
                    # Update the SQL query with the parsed dates
                    date_condition = f"timestamp >= '{start_date}' AND timestamp <= '{end_date}'"
                    
                    # Check if there's already a date condition in the SQL query
                    if 'timestamp >=' in sql_query or 'timestamp <=' in sql_query:
                        # Replace the existing date condition
                        sql_query = re.sub(
                            r"timestamp\s*>=\s*'[^']+'\s*AND\s*timestamp\s*<=\s*'[^']+'",
                            date_condition,
                            sql_query
                        )
                    else:
                        # Add the date condition to the WHERE clause
                        if 'WHERE' in sql_query:
                            sql_query = sql_query.replace('WHERE', f'WHERE {date_condition} AND ')
                        else:
                            # Add a WHERE clause
                            from_match = re.search(r"FROM\s+activities", sql_query, re.IGNORECASE)
                            if from_match:
                                from_pos = from_match.end()
                                sql_query = (
                                    sql_query[:from_pos] + 
                                    f" WHERE {date_condition}" + 
                                    sql_query[from_pos:]
                                )
                else:
                    logger.warning(f"Could not parse date range: '{start_date_str}' to '{end_date_str}'")
            except Exception as e:
                logger.error(f"Error parsing date range: {e}", exc_info=True)
        
        # Check if query is about since a specific date
        elif since_match := since_date_pattern.search(query_text.lower()):
            logger.info("Detected 'since date' query, ensuring correct date range")
            
            # Extract the date
            date_str = since_match.group(1).strip()
            
            # Try to parse the date
            try:
                # Try different date formats
                for date_format in ['%B %d', '%B %d, %Y', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y']:
                    try:
                        # For formats without year, add the current year
                        if '%Y' not in date_format:
                            start_date = datetime.strptime(f"{date_str} {now.year}", f"{date_format} %Y").strftime('%Y-%m-%d')
                        else:
                            start_date = datetime.strptime(date_str, date_format).strftime('%Y-%m-%d')
                        
                        end_date = now.strftime('%Y-%m-%d')
                        
                        logger.info(f"Parsed date range: {start_date} to {end_date}")
                        
                        # Update the SQL query with the parsed dates
                        date_condition = f"timestamp >= '{start_date}' AND timestamp <= '{end_date}'"
                        
                        # Check if there's already a date condition in the SQL query
                        if 'timestamp >=' in sql_query or 'timestamp <=' in sql_query:
                            # Replace the existing date condition
                            sql_query = re.sub(
                                r"timestamp\s*>=\s*'[^']+'\s*AND\s*timestamp\s*<=\s*'[^']+'",
                                date_condition,
                                sql_query
                            )
                        else:
                            # Add the date condition to the WHERE clause
                            if 'WHERE' in sql_query:
                                sql_query = sql_query.replace('WHERE', f'WHERE {date_condition} AND ')
                            else:
                                # Add a WHERE clause
                                from_match = re.search(r"FROM\s+activities", sql_query, re.IGNORECASE)
                                if from_match:
                                    from_pos = from_match.end()
                                    sql_query = (
                                        sql_query[:from_pos] + 
                                        f" WHERE {date_condition}" + 
                                        sql_query[from_pos:]
                                    )
                        
                        break  # Break the loop if parsing succeeds
                    except ValueError:
                        continue  # Try the next format
            except Exception as e:
                logger.error(f"Error parsing date: {e}")
        
        logger.info(f"Post-processed SQL query: {sql_query}")
        return sql_query 