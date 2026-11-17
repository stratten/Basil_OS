"""Shell command checks built on a real shell parser (tree-sitter-bash).

`classify_read_only` proves a command only reads, `find_blocked_command` and `command_matches_pattern` find the commands that must never run, and `inner_shell_script` looks through a `bash -lc '...'` wrapper.
"""

from .commands import collect_commands, find_blocked_command, inner_shell_script
from .patterns import command_matches_pattern
from .read_only import classify_read_only

__all__ = [
    'classify_read_only',
    'collect_commands',
    'command_matches_pattern',
    'find_blocked_command',
    'inner_shell_script',
]
