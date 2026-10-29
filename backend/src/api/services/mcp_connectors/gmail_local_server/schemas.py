"""Input models for the embedded Gmail server, one per tool.

Field names follow Google's hosted Gmail MCP server (``threadId``, ``labelIds``,
``messageFormat``, ...) so the agent sees the same arguments from either server.
The Python attributes are snake_case with a camelCase alias; the JSON schema the
agent reads is generated with aliases.

Every tool that changes the mailbox also accepts an optional ``summary``. Gmail
identifies mail by opaque ids, so the approval prompt would otherwise read
``trash_thread({"threadId":"18f..."})``; the summary is the agent's plain-language
description of what is being changed, shown to the user ahead of the ids.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

MessageFormat = Literal["MESSAGE_FORMAT_UNSPECIFIED", "MINIMAL", "FULL_CONTENT", "METADATA_ONLY", "PLAIN_TEXT", "RAW"]

_SUMMARY_DESCRIPTION = (
    "Optional but strongly recommended. A short plain-language description of what this call changes, "
    "such as the sender and subject of the email, shown to the user in the approval prompt."
)

_QUERY_DESCRIPTION = (
    "Optional. A Gmail search query. Natural language must be converted to Gmail syntax first. Operators include "
    "from:, to:, cc:, subject:, label:<name>, in:inbox, in:sent, in:trash, in:anywhere, is:unread, is:starred, "
    "has:attachment, filename:, larger:, newer_than:7d, older_than:1y, after:YYYY/MM/DD, before:YYYY/MM/DD, "
    "category:promotions, quoted \"exact phrases\", OR, -exclusion, and ( ) grouping. Favor a few distinctive "
    "keywords over a long sentence."
)


class _GmailInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class _MutatingInput(_GmailInput):
    summary: Optional[str] = Field(default=None, description=_SUMMARY_DESCRIPTION)


class SearchThreadsInput(_GmailInput):
    query: Optional[str] = Field(default=None, description=_QUERY_DESCRIPTION)
    page_size: int = Field(default=20, ge=1, le=50, alias="pageSize", description="Optional. Threads to return, 1 to 50. Defaults to 20.")
    page_token: Optional[str] = Field(default=None, alias="pageToken", description="Optional. The nextPageToken from the previous call, to fetch the next page.")
    view: Literal["THREAD_VIEW_UNSPECIFIED", "THREAD_VIEW_METADATA_ONLY", "THREAD_VIEW_MINIMAL"] = Field(
        default="THREAD_VIEW_MINIMAL",
        description="Optional. THREAD_VIEW_MINIMAL (default) includes subject and snippet; THREAD_VIEW_METADATA_ONLY omits them.",
    )
    include_trash: bool = Field(default=False, alias="includeTrash", description="Optional. Include threads in Trash and Spam. Defaults to false.")


class GetThreadInput(_GmailInput):
    thread_id: str = Field(alias="threadId", description="Required. The id of the thread to fetch.")
    message_format: MessageFormat = Field(
        default="FULL_CONTENT",
        alias="messageFormat",
        description="Optional. PLAIN_TEXT is recommended: it returns the text body without HTML. MINIMAL returns subject and snippet only; METADATA_ONLY returns headers and labels only.",
    )


class GetMessageInput(_GmailInput):
    message_id: str = Field(alias="messageId", description="Required. The id of the message to fetch.")
    message_format: MessageFormat = Field(
        default="FULL_CONTENT",
        alias="messageFormat",
        description="Optional. PLAIN_TEXT is recommended: it returns the text body without HTML. MINIMAL returns subject and snippet only; METADATA_ONLY returns headers and labels only; RAW returns the MIME source.",
    )


class ListDraftsInput(_GmailInput):
    query: Optional[str] = Field(default=None, description=_QUERY_DESCRIPTION)
    page_size: int = Field(default=20, ge=1, le=50, alias="pageSize", description="Optional. Drafts to return, 1 to 50. Defaults to 20.")
    page_token: Optional[str] = Field(default=None, alias="pageToken", description="Optional. The nextPageToken from the previous call.")
    view: Literal["DRAFT_VIEW_UNSPECIFIED", "DRAFT_VIEW_METADATA_ONLY", "DRAFT_VIEW_FULL"] = Field(
        default="DRAFT_VIEW_METADATA_ONLY",
        description="Optional. DRAFT_VIEW_FULL adds the subject and plain-text body; the default returns recipients and date only.",
    )


class GetDraftInput(_GmailInput):
    draft_id: str = Field(alias="draftId", description="Required. The id of the draft to fetch.")
    message_format: MessageFormat = Field(default="FULL_CONTENT", alias="messageFormat", description="Optional. Same formats as get_message.")


class ListLabelsInput(_GmailInput):
    pass


class DraftAttachment(_GmailInput):
    path: Optional[str] = Field(
        default=None,
        description="Preferred for any file on the user's computer, including files you saved or created in this task. An absolute path such as /Users/name/Documents/report.pdf, or one starting with ~/. Basil reads the file itself, so you never write its contents. Give this or content, not both.",
    )
    content: Optional[str] = Field(default=None, description="Only for data that is not in a file. The base64-encoded file content; it must be written out in full, so use path instead for any real file. Give this or path, not both.")
    filename: Optional[str] = Field(default=None, description="Optional. The file name recipients see, such as invoice.pdf. With path it defaults to the file's own name.")
    mime_type: Optional[str] = Field(default=None, alias="mimeType", description="Optional. The IANA media type. With path it is worked out from the file name; otherwise it defaults to application/octet-stream.")

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "DraftAttachment":
        has_path = bool(self.path and self.path.strip())
        has_content = bool(self.content)
        if has_path == has_content:
            raise ValueError("Each attachment needs exactly one of path (a file on the user's computer) or content (base64 data).")
        return self


class CreateDraftInput(_MutatingInput):
    to: List[str] = Field(default_factory=list, description="Optional. Primary recipients, each a plain address such as user@example.com. Leave it out on a reply: it defaults to the sender and the other people the original was sent to. If you give it, those addresses are used exactly.")
    cc: List[str] = Field(default_factory=list, description="Optional. Carbon copy recipients, plain addresses. Leave it out on a reply: it defaults to the original Cc list, unless you gave to yourself, in which case nothing is added.")
    bcc: List[str] = Field(default_factory=list, description="Optional. Blind carbon copy recipients, plain addresses.")
    subject: str = Field(default="", description="Optional. The subject line. A reply defaults to Re: plus the original subject.")
    body: str = Field(default="", description="Optional. Plain text body. Do not use Markdown. When htmlBody is also given this is the plain-text alternative.")
    html_body: str = Field(default="", alias="htmlBody", description="Optional. HTML body for rich formatting.")
    reply_to_message_id: Optional[str] = Field(
        default=None,
        alias="replyToMessageId",
        description="Optional. The id of the message being answered. The draft joins its thread and, like Reply All in Mail, is addressed to the sender and everyone else on the original (the user is never added). Write only the new reply: the original is not quoted into the draft, so do not paste it or the earlier thread into the body.",
    )
    reply_all: bool = Field(
        default=True,
        alias="replyAll",
        description="Optional. Defaults to true: a reply goes to everyone on the original, as Reply All does. Set it to false only when the user asked to reply to the sender alone. It has no effect without replyToMessageId or when you give to yourself.",
    )
    include_signature: bool = Field(default=False, alias="includeSignature", description="Optional. Append the user's Gmail signature. Defaults to false.")
    attachments: List[DraftAttachment] = Field(default_factory=list, description="Optional. Files to attach, at most 25MB combined. Give each as a path to a file on the user's computer.")


class DownloadAttachmentInput(_MutatingInput):
    message_id: str = Field(alias="messageId", description="Required. The id of the message that carries the attachment.")
    attachment_id: Optional[str] = Field(
        default=None,
        alias="attachmentId",
        description="Optional. The attachment's attachmentId from get_message. Gmail changes it on every fetch, so prefer filename or partId.",
    )
    part_id: Optional[str] = Field(
        default=None,
        alias="partId",
        description="Optional. The attachment's partId from get_message. It is stable, so use it when two attachments share a file name.",
    )
    filename: Optional[str] = Field(
        default=None,
        description="Optional. The attachment's exact file name from get_message, the simplest way to pick an attachment. Give this or partId.",
    )
    destination_folder: Optional[str] = Field(
        default=None,
        alias="destinationFolder",
        description=(
            "Optional. An absolute folder path, such as /Users/name/Documents or ~/Documents. Leave it out to save into this task's workspace folder; "
            "set it only when the user asked for the file to go somewhere else."
        ),
    )
    save_as: Optional[str] = Field(default=None, alias="saveAs", description="Optional. A different file name to save under. Defaults to the attachment's own name.")


class SendDraftInput(_MutatingInput):
    draft_id: str = Field(alias="draftId", description="Required. The id of an existing draft, from create_draft or list_drafts. Sending cannot compose a new message.")
    recipients: List[str] = Field(
        description="Required. Every recipient address on the draft (To, Cc, and Bcc), exactly as the draft has them. Shown to the user in the approval prompt, and the send is refused if it does not match the draft."
    )
    subject: str = Field(description="Required. The draft's subject line. Shown to the user in the approval prompt, and the send is refused if it does not match the draft.")


class ThreadActionInput(_MutatingInput):
    thread_id: str = Field(alias="threadId", description="Required. The id of the thread.")


class MessageActionInput(_MutatingInput):
    message_id: str = Field(alias="messageId", description="Required. The id of the message.")


_USER_REQUESTED_DESCRIPTION = (
    "Optional. Leave unset when you are undoing your own earlier change. Set true only when the user explicitly asked, in this conversation, "
    "for this specific change to be reversed and Basil did not make it. Without it, the call is refused when Basil has no record of making "
    "the change, because the user or another app most likely did, possibly while you were working."
)


class RestoreThreadInput(ThreadActionInput):
    user_requested: bool = Field(default=False, alias="userRequested", description=_USER_REQUESTED_DESCRIPTION)


class RestoreMessageInput(MessageActionInput):
    user_requested: bool = Field(default=False, alias="userRequested", description=_USER_REQUESTED_DESCRIPTION)


class ThreadLabelsInput(ThreadActionInput):
    label_ids: List[str] = Field(alias="labelIds", min_length=1, description="Required. Label ids: a system id such as INBOX, STARRED, UNREAD, IMPORTANT, or a user label id from list_labels. Names are not accepted.")


class MessageLabelsInput(MessageActionInput):
    label_ids: List[str] = Field(alias="labelIds", min_length=1, description="Required. Label ids: a system id such as INBOX, STARRED, UNREAD, IMPORTANT, or a user label id from list_labels. Names are not accepted.")


class UpdateMessageLabelsInput(MessageActionInput):
    add_label_ids: List[str] = Field(default_factory=list, alias="addLabelIds", description="Optional. Label ids to add.")
    remove_label_ids: List[str] = Field(default_factory=list, alias="removeLabelIds", description="Optional. Label ids to remove.")


class SensitiveThreadLabelInput(ThreadActionInput):
    label_option: Literal["LABEL_OPTION_UNSPECIFIED", "TRASH", "SPAM"] = Field(alias="labelOption", description="Required. TRASH or SPAM.")


class SensitiveMessageLabelInput(MessageActionInput):
    label_option: Literal["LABEL_OPTION_UNSPECIFIED", "TRASH", "SPAM"] = Field(alias="labelOption", description="Required. TRASH or SPAM.")


class CreateLabelInput(_MutatingInput):
    display_name: str = Field(alias="displayName", min_length=1, description="Required. The label name. Use / for nested labels, such as Projects/Alpha.")
    auto_create_parent_labels: bool = Field(default=True, alias="autoCreateParentLabels", description="Optional. Create missing parent labels of a nested name. Defaults to true.")
    color_preset: str = Field(default="LABEL_COLOR_PRESET_UNSPECIFIED", alias="colorPreset", description="Optional. A preset such as LABEL_COLOR_PRESET_RED, LABEL_COLOR_PRESET_BLUE, LABEL_COLOR_PRESET_GREEN or LABEL_COLOR_PRESET_BLACK.")
    label_list_visibility: Literal["LABEL_LIST_VISIBILITY_UNSPECIFIED", "LABEL_SHOW", "LABEL_SHOW_IF_UNREAD", "LABEL_HIDE"] = Field(default="LABEL_SHOW", alias="labelListVisibility", description="Optional. Whether the label shows in Gmail's label list. Defaults to LABEL_SHOW.")
    message_list_visibility: Literal["MESSAGE_LIST_VISIBILITY_UNSPECIFIED", "SHOW", "HIDE"] = Field(default="SHOW", alias="messageListVisibility", description="Optional. Whether messages with the label show in the message list. Defaults to SHOW.")
