"""
Whitelist management for command approval.

Handles CRUD operations for whitelisted command patterns.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

from api.core.models.preferences import CommandPattern

logger = logging.getLogger(__name__)


class WhitelistManager:
    """
    Manages whitelist CRUD operations with security validation.

    Works with command generalization to create reusable patterns and
    PatternMatcher to validate security constraints.
    """

    def __init__(self, generalizer, pattern_matcher):
        self.generalizer = generalizer
        self.pattern_matcher = pattern_matcher

    async def add_to_whitelist(
        self,
        command: str,
        pattern_type: str = 'exact',
        description: str = '',
        risk_level: str = 'low',
        record_initial_use: bool = False
    ) -> CommandPattern:
        """Add a command to the whitelist.

        ``record_initial_use`` counts the approved execution that created the pattern; manual additions leave it unset.
        """
        try:
            pattern_to_save = self.generalizer.generalize_command(command)

            if self.pattern_matcher.is_naked_wrapper(pattern_to_save):
                error_msg = (
                    f"Cannot whitelist naked shell wrapper: '{pattern_to_save}'. "
                    f"This would allow ANY command through that shell. "
                    f"Original command: '{command[:100]}...'"
                )
                logger.error(f"🚨 SECURITY REJECTION: {error_msg}")
                raise ValueError(error_msg)

            from api.core.preferences.preferences_io import load_preferences, save_preferences
            preferences = load_preferences()

            for existing_pattern in preferences.tool_execution.whitelisted_commands:
                if existing_pattern.pattern == pattern_to_save and existing_pattern.pattern_type == 'prefix':
                    logger.info(f"Pattern '{pattern_to_save}' already exists in whitelist, skipping duplicate")
                    return existing_pattern

            added_at = datetime.now()
            new_pattern = CommandPattern(
                id=str(uuid.uuid4()),
                pattern=pattern_to_save,
                pattern_type='prefix',
                description=description or f"Generalized from: {command[:100]}...",
                added_date=added_at,
                risk_level=risk_level,
                use_count=1 if record_initial_use else 0,
                last_used=added_at if record_initial_use else None,
            )

            preferences.tool_execution.whitelisted_commands.append(new_pattern)
            save_preferences(preferences)

            logger.info(f"✅ Added command to whitelist: {pattern_to_save} (type: prefix, original: {command[:100]}...)")
            return new_pattern

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error adding command to whitelist: {e}", exc_info=True)
            raise

    async def update_whitelist_pattern(
        self,
        pattern_id: str,
        command: str,
        pattern_type: str = 'exact',
        description: str = ''
    ) -> Optional[CommandPattern]:
        """Update an existing whitelist pattern."""
        try:
            from api.core.preferences.preferences_io import load_preferences, save_preferences
            preferences = load_preferences()

            for pattern in preferences.tool_execution.whitelisted_commands:
                if pattern.id == pattern_id:
                    pattern.pattern = command
                    pattern.pattern_type = pattern_type
                    pattern.description = description

                    save_preferences(preferences)

                    logger.info(f"Updated whitelist pattern: {pattern_id} to '{command}' (type: {pattern_type})")
                    return pattern

            logger.warning(f"Pattern not found in whitelist: {pattern_id}")
            return None

        except Exception as e:
            logger.error(f"Error updating whitelist pattern: {e}", exc_info=True)
            raise

    async def remove_from_whitelist(self, pattern_id: str) -> bool:
        """Remove a pattern from the whitelist."""
        try:
            from api.core.preferences.preferences_io import load_preferences, save_preferences
            preferences = load_preferences()
            whitelist = preferences.tool_execution.whitelisted_commands

            original_length = len(whitelist)
            preferences.tool_execution.whitelisted_commands = [
                p for p in whitelist if p.id != pattern_id
            ]

            if len(preferences.tool_execution.whitelisted_commands) < original_length:
                save_preferences(preferences)
                logger.info(f"Removed pattern from whitelist: {pattern_id}")
                return True

            logger.warning(f"Pattern not found in whitelist: {pattern_id}")
            return False

        except Exception as e:
            logger.error(f"Error removing from whitelist: {e}", exc_info=True)
            raise

    async def update_pattern_usage(self, pattern_id: str) -> None:
        """Update usage statistics for a whitelisted pattern."""
        try:
            from api.core.preferences.preferences_io import load_preferences, save_preferences
            preferences = load_preferences()

            for pattern in preferences.tool_execution.whitelisted_commands:
                if pattern.id == pattern_id:
                    pattern.use_count += 1
                    pattern.last_used = datetime.now()
                    save_preferences(preferences)
                    logger.debug(f"Updated usage stats for pattern: {pattern_id}")
                    return

            logger.warning(f"Cannot record usage; pattern not found in whitelist: {pattern_id}")

        except Exception as e:
            logger.error(f"Error updating pattern usage: {e}", exc_info=True)
