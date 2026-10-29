"""In-process Gmail tools that call the Gmail API directly.

Google's hosted Gmail MCP server (``gmailmcp.googleapis.com``) is a Developer
Preview feature: it refuses every tool call from a Google Cloud project that has
not been enrolled in the Google Workspace Developer Preview Program, however
correct the sign-in is. The Gmail API itself has no such gate. This package
exposes the same tools, with the same names and arguments, on top of the Gmail
API, so Basil can read, draft, label, trash, and send mail today and the agent
cannot tell the difference.

It follows the same pattern as ``slack_local_server``:

  * **Same connection.** The record keeps the hosted server URL, so sign-in,
    Keychain tokens, token refresh, reconnecting, and Settings all work
    unchanged. ``MCPClientService`` routes Gmail calls here while
    :func:`transport.gmail_uses_direct_api` is true.
  * **Same envelopes.** ``list_tools`` returns the catalog dict and ``call_tool``
    a normalized envelope, exactly as the remote path does.
  * **Stateless and lazy.** The package is imported on first use, and each call
    opens and closes its own HTTP client.
  * **No permanent delete.** Deleting means Trash. The OAuth scope Basil
    requests (``gmail.modify``) cannot delete permanently, and no tool tries.

Layout:

  * ``schemas.py``         input models, one per tool
  * ``gmail_api.py``       the authenticated REST client and its errors
  * ``message_shaping.py`` Gmail message JSON to the agent's format
  * ``mime_builder.py``    draft construction
  * ``handlers_read.py``   search, read, list
  * ``handlers_write.py``  drafts, send, labels, Trash, Spam
  * ``error_mapping.py``   Gmail failures to standard envelopes
  * ``transport.py``       the direct-API versus hosted-MCP switch
  * ``server.py``          the tool registry, ``list_tools``, and ``call_tool``

Nothing is imported here on purpose: ``MCPClientService`` imports
``gmail_local_server.transport`` to choose a route and ``gmail_local_server.server``
only when a Gmail call is really made, so an idle Basil never loads the handlers.
"""
