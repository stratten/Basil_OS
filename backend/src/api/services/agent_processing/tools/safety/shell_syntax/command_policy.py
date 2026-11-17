"""The command lists and argument rules behind the shell command checks.

They sit apart from the parsing code so a list can be read, or changed, without reading any parser logic. A name on READ_ONLY_COMMANDS is read-only whatever its arguments, except where `violates_argument_policy` says the arguments change that.
"""

from __future__ import annotations

import re
from typing import Dict, FrozenSet, List

BLOCKED_COMMANDS: FrozenSet[str] = frozenset({
    'rm', 'shred', 'wipe', 'srm',
    'dd', 'mkfs', 'fdisk', 'parted', 'diskutil',
    'shutdown', 'reboot', 'halt', 'poweroff', 'init',
    'sudo', 'su', 'doas',
    'umount', 'mount',
})

# Programs that start another program on their own behalf, so `env rm x`, `nohup rm x` and `xargs rm` run `rm`. The program they start is the first word that is not one of their own options or a `NAME=value` assignment. Each value lists the options that take a value, because that value is not the program (`nice -n 10 rm`, `env -u HOME rm`).
LAUNCHER_COMMANDS: Dict[str, FrozenSet[str]] = {
    'env': frozenset({'-u', '-C', '-S', '-P'}),
    'xargs': frozenset({'-n', '-I', '-L', '-P', '-s', '-d', '-E', '-a', '-R', '-S'}),
    'nohup': frozenset(),
    'nice': frozenset({'-n'}),
    'time': frozenset({'-f', '-o'}),
    'timeout': frozenset({'-s', '-k'}),
    'command': frozenset(),
    'exec': frozenset({'-a'}),
    'builtin': frozenset(),
    'stdbuf': frozenset({'-i', '-o', '-e'}),
    'caffeinate': frozenset({'-t', '-w'}),
    'setsid': frozenset(),
    'ionice': frozenset({'-c', '-n', '-p'}),
    'arch': frozenset({'-arch'}),
}

# `find` runs the command that follows any of these once for each match.
FIND_EXEC_PREDICATES: FrozenSet[str] = frozenset({'-exec', '-execdir', '-ok', '-okdir'})

READ_ONLY_COMMANDS: FrozenSet[str] = frozenset({
    'ls', 'dir', 'cat', 'head', 'tail', 'grep', 'find', 'wc',
    'pwd', 'echo', 'date', 'whoami', 'which', 'file', 'stat',
    'df', 'du', 'ps', 'top', 'env', 'printenv', 'history',
    # Text and path helpers. `sort -o` and `uniq <in> <out>` write a file, and violates_argument_policy refuses those forms.
    'sort', 'uniq', 'cut', 'tr', 'diff', 'jq', 'shasum', 'basename', 'dirname', 'realpath', 'readlink',
    # Facts about the machine and its processes.
    'uname', 'sw_vers', 'hostname', 'id', 'uptime', 'lsof', 'pgrep',
    # Spotlight lookups: `mdfind` searches the index and `mdls` prints a file's metadata. Neither has an option that writes; changing the index belongs to `mdutil`, which stays off this list.
    'mdfind', 'mdls',
    # Shell builtins that change nothing outside the shell. `exit` only ends the shell, which is how `cd x || exit 1` stops when the folder is missing. `for`, `done`, and `fi` stay because assess_risk_level reads the first word of a command string; the parse tree never reports them as command names.
    'cd', 'test', 'sleep', 'printf', 'for', 'done', 'fi', 'exit',
})

# Read-only only in one form, which violates_argument_policy enforces. They stay out of READ_ONLY_COMMANDS so assess_risk_level does not rate `sed -i`, `defaults write`, or `command rm` as low risk.
CONDITIONALLY_READ_ONLY_COMMANDS: FrozenSet[str] = frozenset({'sed', 'git', 'defaults', 'command'})

# `command -v jq` prints where a program is and runs nothing. Without the flag `command` runs its argument, so only these two flags are read-only.
COMMAND_LOOKUP_FLAGS: FrozenSet[str] = frozenset({'-v', '-V'})

READ_ONLY_SUBCOMMANDS: Dict[str, FrozenSet[str]] = {
    'git': frozenset({'status', 'log', 'diff'}),
    'defaults': frozenset({'read', 'read-type', 'domains', 'find'}),
}

# `sed -n` with one literal print script (`5p`, `1,20p`, `$p`, `/text/p`). Any other script can write a file (`w`) or run a command (`e`).
SED_PRINT_SCRIPT = re.compile(r'^((\d+|\$)(,(\d+|\$))?|/[A-Za-z0-9 _.:-]*/)p$')
# `sed 's/old/new/g'` with the `/` delimiter and only the flags `g`, `I`, `p`, and a number. The `w` flag writes a file and `e` runs a command, so neither is allowed. The pattern and the replacement hold no `$` (except the end-of-line `$` right before the closing `/`) and no backtick, which keeps the rule stricter than the shell needs and identical to the rule the old tokenizer enforced.
SED_SUBSTITUTE_SCRIPT = re.compile(r'^s/(?:[^/\\\n$`]|\\[^$`\n]|\$(?=/))*/(?:[^/\\\n$`]|\\[^$`\n])*/[gIp0-9]*$')
# Options that change how `sed` reads its script and prints, and nothing else. `-i` edits the file and `-f` reads a script file that may hold `w`, so both stay out.
SED_SAFE_OPTIONS: FrozenSet[str] = frozenset({'-E', '-r', '-n'})

# A `$(...)` is accepted only as an argument of these, which print what they are given and never act on it.
PRINT_ONLY_COMMANDS: FrozenSet[str] = frozenset({'echo', 'printf'})

# How many `$(...)` levels and shell wrappers (`bash -c '...'`) the checks follow. The same number applies to both.
MAX_NESTING_DEPTH = 3

# `uniq <input> <output>` writes the second file and `hostname <name>` sets the name, so these take no more positional arguments than this.
MAX_POSITIONAL_ARGUMENTS: Dict[str, int] = {'uniq': 1, 'hostname': 0}

FIND_MUTATING_PREDICATES: FrozenSet[str] = frozenset({'-delete', '-exec', '-execdir', '-ok', '-okdir', '-fprint', '-fprint0', '-fprintf', '-fls'})

# Flags that turn an otherwise read-only command into one that changes state. `env` has no entry here: it is read-only only when run on its own.
MUTATING_ARGUMENTS: Dict[str, FrozenSet[str]] = {
    'history': frozenset({'-c', '-d', '-a', '-n', '-r', '-w', '-s', '-p'}),
    'date': frozenset({'-s', '--set'}),
    'file': frozenset({'-C', '--compile'}),
    'sort': frozenset({'-o', '--output', '--compress-program'}),
    'hostname': frozenset({'-F', '--file'}),
    'git': frozenset({'--output', '--ext-diff'}),
}

# The words after the redirection operator that mean "write nothing": the null device.
NULL_REDIRECTION_TARGET = '/dev/null'

# A program named with a path is read-only only when the path is one of these system folders. `./ls` or `/tmp/x/ls` would run whatever file sits there under a read-only name.
SYSTEM_COMMAND_DIRECTORIES: FrozenSet[str] = frozenset({
    '/bin', '/usr/bin', '/sbin', '/usr/sbin', '/usr/local/bin', '/opt/homebrew/bin',
})

# Commands whose safety depends on the value of their arguments. Their arguments must be plain text the parser can read, because a value computed by the shell could be an option (`-delete`, `-i`, `--output`) that changes what the command does.
ARGUMENT_POLICY_COMMANDS: FrozenSet[str] = (
    frozenset({'find', 'env', 'sed', 'command'})
    | frozenset(READ_ONLY_SUBCOMMANDS)
    | frozenset(MAX_POSITIONAL_ARGUMENTS)
    | frozenset(MUTATING_ARGUMENTS)
)

MODIFYING_COMMANDS: FrozenSet[str] = frozenset({
    'mv', 'cp', 'mkdir', 'rmdir', 'touch', 'chmod', 'chown',
    'ln', 'tar', 'zip', 'unzip', 'git', 'curl', 'wget',
})

HIGH_RISK_COMMANDS: FrozenSet[str] = frozenset({
    'systemctl', 'service', 'kill', 'killall', 'pkill',
})


def is_print_only_sed(arguments: List[str]) -> bool:
    """Whether the arguments are `-n`, one literal print script, and then only file names."""
    if len(arguments) < 2 or arguments[0] != '-n' or not SED_PRINT_SCRIPT.match(arguments[1]):
        return False
    return not any(argument.startswith('-') and argument != '-' for argument in arguments[2:])


def is_plain_substitution_sed(arguments: List[str]) -> bool:
    """Whether the arguments are safe options, one plain `s/old/new/` script (alone or after `-e`), and then only file names."""
    index = 0
    while index < len(arguments) and arguments[index] in SED_SAFE_OPTIONS:
        index += 1
    if index < len(arguments) and arguments[index] == '-e':
        index += 1
    if index >= len(arguments) or not SED_SUBSTITUTE_SCRIPT.match(arguments[index]):
        return False
    return not any(argument.startswith('-') and argument != '-' for argument in arguments[index + 1:])


def violates_argument_policy(name: str, arguments: List[str]) -> bool:
    """Whether a command that is read-only by name is unsafe because of these plain-text arguments. Redirections are not arguments and never reach this function."""
    if name == 'find' and any(argument in FIND_MUTATING_PREDICATES for argument in arguments):
        return True
    if name == 'env':
        # `env` alone prints the environment. Anything after it is a command it runs, an assignment that feeds one, or a flag that changes how it runs.
        return bool(arguments)
    allowed_subcommands = READ_ONLY_SUBCOMMANDS.get(name)
    if allowed_subcommands is not None and (not arguments or arguments[0] not in allowed_subcommands):
        # The subcommand has to come first: `git -c core.pager=<command> log` would run that command.
        return True
    if name == 'sed' and not (is_print_only_sed(arguments) or is_plain_substitution_sed(arguments)):
        return True
    if name == 'command' and (not arguments or arguments[0] not in COMMAND_LOOKUP_FLAGS):
        # `command rm x` runs `rm`, and `command -p ls` runs `ls` with a different search path, so the lookup flag has to come first.
        return True
    maximum = MAX_POSITIONAL_ARGUMENTS.get(name)
    if maximum is not None and sum(1 for argument in arguments if not argument.startswith('-')) > maximum:
        return True
    forbidden = MUTATING_ARGUMENTS.get(name)
    if not forbidden:
        return False
    short_letters = {flag[1] for flag in forbidden if len(flag) == 2}
    long_flags = {flag for flag in forbidden if flag.startswith('--')}
    for argument in arguments:
        if argument in forbidden:
            return True
        if argument.startswith('--'):
            # GNU tools accept any unambiguous prefix, so `--out` means `--output`, and `--output=file` carries its value.
            flag_name = argument.split('=', 1)[0]
            if len(flag_name) > 2 and any(flag.startswith(flag_name) for flag in long_flags):
                return True
        # Short flags can be combined, so `-us` carries `-s`.
        elif argument.startswith('-') and short_letters.intersection(argument[1:]):
            return True
    return False
