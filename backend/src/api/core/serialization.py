"""Custom serialization utilities for consistent API responses."""

from datetime import datetime
import json
from typing import Any
from pydantic import BaseModel


class StandardJSONEncoder(json.JSONEncoder):
    """JSON encoder that formats datetimes consistently for Swift compatibility.
    This encoder formats datetime objects without microseconds to ensure
    Swift's ISO8601DateFormatter can parse them reliably.
    """
    
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            # Format without microseconds for Swift compatibility
            # Using 'Z' suffix for UTC timezone
            return obj.strftime('%Y-%m-%dT%H:%M:%SZ')
        return super().default(obj)


class APIBaseModel(BaseModel):
    """Base model for API responses with consistent datetime serialization.
    All API models should inherit from this to ensure datetime fields
    are serialized in a format compatible with Swift's date decoders.
    """
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.strftime('%Y-%m-%dT%H:%M:%SZ') if v else None
        }
        # Allow population by field name or alias
        populate_by_name = True

