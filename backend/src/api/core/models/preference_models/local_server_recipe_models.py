"""The recipe a local server can carry: what it needs installed, how Basil gets the program, and how Basil can tell it is healthy.

Nothing here names a particular program. A recipe is data the person or the agent supplies and the person approves, so it can describe any bridge or tool. Hashes and commits are pinned so that, once approved, the source cannot change underneath the person. Secrets never appear in a recipe.
"""

from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

ProbePhase = Literal["starting", "ready", "needs_action", "failed"]
ProbeAuth = Literal["none", "bearer_run_secret", "bearer_secret"]
ArchiveKind = Literal["tar.gz", "zip"]


class MCPRequirement(BaseModel):
    """A program the recipe needs on this Mac before it can acquire or build anything."""
    name: str = Field(..., description="Short name shown to the person, such as the program's own name")
    reason: str = Field(..., description="One sentence saying why it is needed, shown when Basil asks permission to install it")
    check: List[str] = Field(..., description="Command and arguments run without a shell; exit code 0 means the requirement is met")
    install: Optional[List[str]] = Field(default=None, description="Command and arguments that install it, run only after the person approves that step; omit when the person must install it themselves")
    for_method: Literal["any", "download", "build"] = Field(default="any", description="Which acquire method needs it; a build-only requirement is skipped when a download is used")


class MCPBuildStep(BaseModel):
    """One command of a build, run inside the checked-out source."""
    argv: List[str] = Field(..., description="Command and arguments run without a shell")
    cwd: Optional[str] = Field(default=None, description="Folder inside the checked-out source to run in; relative, never leaving the source")


class MCPDownloadMethod(BaseModel):
    """Fetch a prebuilt file over https and check it against a pinned hash."""
    kind: Literal["download"] = "download"
    url: str = Field(..., description="https address; {os} becomes darwin and {arch} becomes arm64 or amd64")
    sha256: Optional[str] = Field(default=None, description="Hash of the file when it is the same on every architecture")
    sha256_by_arch: Dict[str, str] = Field(default_factory=dict, description="Hash of the file per architecture, keyed arm64 or amd64")
    archive: Optional[ArchiveKind] = Field(default=None, description="Set when the download is an archive to unpack into the artifact's path")
    strip_components: int = Field(default=0, ge=0, le=3, description="Leading folder levels dropped while unpacking an archive")
    executable: bool = Field(default=True, description="Mark the downloaded file executable; ignored for archives")


class MCPBuildMethod(BaseModel):
    """Check out a pinned commit and build it."""
    kind: Literal["build"] = "build"
    git_url: str = Field(..., description="https address of the repository")
    commit: str = Field(..., description="Full 40-character commit the build is pinned to; a branch or tag name is not accepted")
    steps: List[MCPBuildStep] = Field(default_factory=list, description="Commands run in order inside the checked-out source")


MCPAcquireMethod = Annotated[Union[MCPDownloadMethod, MCPBuildMethod], Field(discriminator="kind")]


class MCPArtifact(BaseModel):
    """One thing Basil must put in place, with the ways it can be obtained."""
    name: str = Field(..., description="Short name shown while it is being prepared")
    expects: str = Field(..., description="Path, relative to {install_dir}, that must exist once it is in place; a download is saved here and a build must produce it")
    methods: List[MCPAcquireMethod] = Field(..., description="Ways to obtain it, in the order to try them")


class MCPInstallRecipe(BaseModel):
    """Everything Basil prepares before a local server first runs."""
    requirements: List[MCPRequirement] = Field(default_factory=list, description="Programs that must be present first")
    artifacts: List[MCPArtifact] = Field(default_factory=list, description="Files or folders Basil puts under {install_dir}")


class MCPProbeSpec(BaseModel):
    """How Basil asks a running background program whether it is healthy or waiting on the person."""
    url: str = Field(..., description="Loopback http or https address that contains {port}")
    auth: ProbeAuth = Field(default="none", description="none, the per-run secret as a bearer token, or a declared secret as a bearer token")
    secret_name: Optional[str] = Field(default=None, description="Name of a declared secret, required when auth is bearer_secret")
    state_path: str = Field(..., description="Dotted path of the state value in the JSON answer, such as state or status.phase")
    states: Dict[str, ProbePhase] = Field(..., description="Maps each state value the program reports to starting, ready, needs_action or failed; an unmapped value counts as starting")
    message_path: Optional[str] = Field(default=None, description="Dotted path of a plain-language message to show the person")
    action_kind: Optional[Literal["qr"]] = Field(default=None, description="What an action value is; qr is a code the person scans")
    action_path: Optional[str] = Field(default=None, description="Dotted path of the action value, used while the phase is needs_action")
    expires_path: Optional[str] = Field(default=None, description="Dotted path of when the action value expires, as an ISO time")
    interval_seconds: float = Field(default=3.0, ge=1.0, le=30.0, description="Seconds between checks")
