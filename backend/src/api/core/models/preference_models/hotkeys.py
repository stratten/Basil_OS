"""Hotkey preference models."""

from typing import List, Optional

from pydantic import BaseModel, Field


class HotkeyBinding(BaseModel):
    """Represents a single hotkey binding."""
    key: str = Field(..., description="The key (e.g., 'F9')")
    modifiers: List[str] = Field(default_factory=list, description="List of modifiers (e.g., ['ctrl', 'shift'])")
    enabled: bool = Field(default=True, description="Whether this hotkey is enabled")
    description: str = Field(default="", description="Description of what this hotkey does")
    # Double-press modifier support (e.g., Option+Option instead of Option+Space)
    is_double_press: bool = Field(default=False, description="Whether this is a double-press modifier binding")
    double_press_key: Optional[str] = Field(default=None, description="The modifier key to double-press (option, command, control, shift)")


class HotkeySettings(BaseModel):
    """Hotkey configuration settings."""
    # Testing Features (F1)
    capture_screen: HotkeyBinding = Field(
        default_factory=lambda: HotkeyBinding(key="F1", modifiers=[], enabled=True)
    )

    # Audio/Transcription Features - Cmd+Cmd (double-press command) by default
    transcribe_audio: HotkeyBinding = Field(
        default_factory=lambda: HotkeyBinding(
            key="",
            modifiers=[],
            enabled=True,
            is_double_press=True,
            double_press_key="command",
            description="Push-to-talk transcription"
        )
    )
    streaming_transcription: HotkeyBinding = Field(
        default_factory=lambda: HotkeyBinding(key="F5", modifiers=[], enabled=True)
    )

    # Core Conversation Features (F8-F12). The legacy `get_suggestions`
    # (F9) and `enhanced_suggestions` (F10) bindings were removed as part
    # of the assistant-session unification -- both modalities now live behind
    # the unified `assistant_session` hotkey with an in-widget speak/type toggle.
    conversation_toggle: HotkeyBinding = Field(
        default_factory=lambda: HotkeyBinding(key="F8", modifiers=[], enabled=True)
    )
    insert_assistant_output: HotkeyBinding = Field(
        default_factory=lambda: HotkeyBinding(key="F12", modifiers=[], enabled=True)
    )

    # Assistant-session Hotkey - Option+Option (double-press option) by default
    assistant_session: HotkeyBinding = Field(
        default_factory=lambda: HotkeyBinding(
            key="",
            modifiers=[],
            enabled=True,
            is_double_press=True,
            double_press_key="option",
            description="Show the assistant-session UI"
        )
    )

    # Agent-task Hotkey - Option+Space by default
    agent_task: HotkeyBinding = Field(
        default_factory=lambda: HotkeyBinding(
            key="Space",
            modifiers=["option"],
            enabled=True,
            description="Start/stop agent-task capture"
        )
    )

    # Basil Home (BasilBoard) toggle -- Control+Option+B by default.
    home_board_toggle: HotkeyBinding = Field(
        default_factory=lambda: HotkeyBinding(
            key="B",
            modifiers=["control", "option"],
            enabled=True,
            description="Show or hide the Basil Home board"
        )
    )
