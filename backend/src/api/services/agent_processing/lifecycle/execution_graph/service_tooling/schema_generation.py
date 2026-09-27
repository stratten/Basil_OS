"""Schema generation helpers for service-backed LangChain tools."""

from typing import Any, Dict, List, Literal, Optional, Type

from .models import BaseModel, Field, LANGCHAIN_AVAILABLE, create_model

if LANGCHAIN_AVAILABLE:
    try:
        from pydantic import model_validator
        from ....tools.direct_application_interactions.email_integration.email_tool_contracts import (
            CreateNewEmailDraftArgs,
            CreateReplyEmailDraftArgs,
            ExpandEmailDetailsArgs,
            GetEmailMetadataArgs,
            GetEmailsArgs,
            SearchEmailsArgs,
        )
        from ....tools.direct_application_interactions.email_integration.email_operation_contracts import (
            BulkOrganizeEmailsArgs,
            OrganizeEmailsArgs,
        )
    except ImportError:
        CreateNewEmailDraftArgs = None
        CreateReplyEmailDraftArgs = None
        ExpandEmailDetailsArgs = None
        GetEmailMetadataArgs = None
        GetEmailsArgs = None
        SearchEmailsArgs = None
        BulkOrganizeEmailsArgs = None
        OrganizeEmailsArgs = None
        model_validator = None
else:
    CreateNewEmailDraftArgs = None
    CreateReplyEmailDraftArgs = None
    ExpandEmailDetailsArgs = None
    GetEmailMetadataArgs = None
    GetEmailsArgs = None
    SearchEmailsArgs = None
    BulkOrganizeEmailsArgs = None
    OrganizeEmailsArgs = None
    model_validator = None


if LANGCHAIN_AVAILABLE:
    class ShellFileOperationArgs(BaseModel):
        """One exact filesystem transition expected from a shell command."""

        operation: Literal["create", "modify", "copy", "move", "rename", "delete"]
        path: str
        source_path: Optional[str] = None

        @model_validator(mode="after")
        def validate_source_path(self):
            if self.operation in {"copy", "move", "rename"} and not self.source_path:
                raise ValueError(f"source_path is required for {self.operation}.")
            return self


    class ShellExecuteCommandArgs(BaseModel):
        command: str = Field(description="Executable name only, such as 'bash', 'rg', or 'git'.")
        args: Optional[List[str]] = Field(default=None, description="Native argv vector. Send a JSON array of strings such as [\"-lc\", \"printf '%s\\n' hello\"], never a quoted or double-serialized JSON array string. For plain text-file writes, use file_service_write_text_file instead of shell redirection so content is passed directly.")
        cwd: Optional[str] = Field(default=None, description="Optional allowlisted working directory.")
        env_overrides: Optional[Dict[str, str]] = Field(default=None, description="Optional explicit string environment-variable overrides.")
        timeout_s: Optional[int] = Field(default=None, description="Optional timeout in seconds, capped by the shell service at 60 seconds.")
        max_output_bytes: Optional[int] = Field(default=None, description="Optional per-stream output cap in bytes.")
        file_operations: Optional[List[ShellFileOperationArgs]] = Field(default=None, description="Exact declared filesystem transitions for a shell mutation. Each path must be absolute and within the allowed roots.")
        skip_approval_check: bool = Field(default=False, description="Internal-only flag for tests and trusted service composition; agents must not set it.")

    class WriteTextFileArgs(BaseModel):
        path: str = Field(description="Absolute target path inside the user home directory or Basil backend repository root. The path must not traverse a symbolic link.")
        content: str = Field(description="Exact UTF-8 text to write. Pass the text directly; do not JSON-stringify it and do not use shell quoting or redirection.")
        mode: Literal["create", "overwrite", "append"] = Field(description="create requires an absent target; overwrite replaces an existing regular file; append adds text to an existing regular file.")
        expected_sha256: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{64}$", description="Optional lowercase SHA-256 digest of the current file. When supplied for overwrite or append, the tool refuses a stale target instead of modifying it.")
else:
    ShellFileOperationArgs = object
    ShellExecuteCommandArgs = object
    WriteTextFileArgs = object


def get_explicit_input_model(service_name: str, method_name: str) -> Optional[Type[BaseModel]]:
    """Return compact explicit schemas for selected high-risk service methods."""
    if service_name == "shell_service" and method_name == "execute_command":
        return ShellExecuteCommandArgs
    if service_name == "file_service" and method_name == "write_text_file":
        return WriteTextFileArgs
    if service_name != "email_service":
        return None

    explicit_models = {
        "get_emails": GetEmailsArgs,
        "get_email_metadata": GetEmailMetadataArgs,
        "expand_email_details": ExpandEmailDetailsArgs,
        "search_emails": SearchEmailsArgs,
        "create_new_email_draft": CreateNewEmailDraftArgs,
        "create_reply_email_draft": CreateReplyEmailDraftArgs,
        "organize_emails": OrganizeEmailsArgs,
        "bulk_organize_emails": BulkOrganizeEmailsArgs,
    }
    return explicit_models.get(method_name)


def create_input_model(tool_name: str, method_info: Dict[str, Any]) -> Type[BaseModel]:
    """Create a dynamic Pydantic model for tool input parameters."""
    parameters = method_info.get("parameters", {})

    if not parameters:
        # Create empty model for methods with no parameters
        return create_model(f"{tool_name}Input", __base__=BaseModel)

    # Build field definitions for Pydantic model
    field_definitions = {}

    for param_name, param_info in parameters.items():
        param_type = convert_type_string_to_python_type(param_info.get("type", "Any"))
        required = param_info.get("required", False)
        description = param_info.get("description", f"Parameter {param_name}")
        default_value = param_info.get("default")

        if required:
            field_definitions[param_name] = (param_type, Field(description=description))
        else:
            default = default_value if default_value is not None else None
            field_definitions[param_name] = (Optional[param_type], Field(default=default, description=description))

    return create_model(f"{tool_name}Input", **field_definitions, __base__=BaseModel)


def convert_type_string_to_python_type(type_string: str) -> Type:
    """Convert string type annotations to Python types for Pydantic."""
    type_mapping = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "Dict[str, Any]": Dict[str, Any],
        "List[str]": List[str],
        "Optional[str]": Optional[str],
        "Any": Any,
    }

    # Handle complex types by defaulting to Any
    return type_mapping.get(type_string, Any)
