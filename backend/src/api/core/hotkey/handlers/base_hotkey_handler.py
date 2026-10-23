"""Base class for hotkey event handlers."""

from typing import Optional, Any
import asyncio
from datetime import datetime

from ...models.preferences import Preferences

class BaseHotkeyHandler:
    """Base class for handling hotkey events and their associated operations."""

    def __init__(self, preferences: Preferences, event_loop: asyncio.AbstractEventLoop):
        """Initialize the hotkey handler.
        
        Args:
            preferences: Application preferences containing hotkey bindings
            event_loop: The asyncio event loop to use for async hotkey operations
        """
        self.preferences = preferences
        self._loop = event_loop
        self._current_operation: Optional[str] = None
        self._operation_start_time: Optional[datetime] = None
        self._widget: Optional[Any] = None

    async def handle_key_press(self, key: str) -> None:
        """Handle a key press event.
        
        Args:
            key: The key that was pressed
        """
        raise NotImplementedError("Subclasses must implement handle_key_press")

    async def handle_key_release(self, key: str) -> None:
        """Handle a key release event.
        
        Args:
            key: The key that was released
        """
        raise NotImplementedError("Subclasses must implement handle_key_release")

    def set_widget(self, widget: Any) -> None:
        """Set the widget associated with this handler.
        
        Args:
            widget: The widget to associate with this handler
        """
        self._widget = widget

    def cleanup(self) -> None:
        """Clean up any resources used by this handler."""
        self._current_operation = None
        self._operation_start_time = None
        self._widget = None

    def _start_operation(self, operation_name: str) -> None:
        """Start a new operation.
        
        Args:
            operation_name: The name of the operation being started
        """
        self._current_operation = operation_name
        self._operation_start_time = datetime.now()

    def _complete_operation(self, operation_name: str) -> None:
        """Complete an operation.
        
        Args:
            operation_name: The name of the operation being completed
        """
        if self._current_operation == operation_name:
            self._current_operation = None
            self._operation_start_time = None

    def _handle_error(self, error_msg: str) -> None:
        """Handle an error that occurred during operation.
        
        Args:
            error_msg: The error message to emit
        """
        self._current_operation = None
        self._operation_start_time = None 