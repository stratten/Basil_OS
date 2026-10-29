import Foundation

/// WebSocket bridge for the provider API keys the user supplied.
///
/// The Python backend never writes provider keys to the Keychain itself. Over the live `/ws` connection it asks this client for the keys when it connects (`provider_keys_request`), and asks it to save or remove one (`provider_key_store`, `provider_key_delete`). The client keeps the keys in the shared ``CredentialVault``, the same single Keychain item that holds the account session and the MCP connection tokens, so macOS asks for permission once. Key values are never written to a log.
enum WebSocketService_ProviderKeys {
    /// Correlation ids of snapshot requests already answered. The backend repeats a request with the same id while it waits, and a repeat that arrives while the first is blocked on a macOS permission prompt must not raise a second prompt after the user answered the first.
    @MainActor private static var answeredSnapshotIds: [String] = []

    /// Answers `provider_keys_request` with every provider key in the vault, or `status: unavailable` when the vault exists but cannot be read. A repeat of an already answered request is ignored.
    @MainActor
    static func handleKeysRequest(
        _ json: [String: Any],
        vault: CredentialVault? = nil,
        send: (String) -> Void
    ) {
        let vault = vault ?? .shared
        guard let correlationId = json["correlation_id"] as? String else {
            DevLogger.shared.error("🔑 provider_keys_request missing correlation_id", context: "websocket")
            return
        }
        guard !answeredSnapshotIds.contains(correlationId) else {
            DevLogger.shared.info("🔑 Ignoring a repeated provider_keys_request", context: "websocket")
            return
        }
        answeredSnapshotIds.append(correlationId)
        if answeredSnapshotIds.count > 16 {
            answeredSnapshotIds.removeFirst()
        }
        var response: [String: Any] = [
            "type": "provider_keys_snapshot",
            "correlation_id": correlationId
        ]
        if let contents = vault.load() {
            response["status"] = "ok"
            response["keys"] = contents.providerKeys
            DevLogger.shared.info(
                "🔑 Sending \(contents.providerKeys.count) provider key(s) to the backend",
                context: "websocket"
            )
        } else {
            response["status"] = "unavailable"
            response["keys"] = [String: String]()
            DevLogger.shared.error("🔑 The Keychain vault could not be read; reporting provider keys unavailable", context: "websocket")
        }
        sendJSON(response, send: send)
    }

    /// Saves one provider key into the vault and acknowledges with `provider_key_result`.
    @MainActor
    static func handleKeyStore(
        _ json: [String: Any],
        vault: CredentialVault? = nil,
        send: (String) -> Void
    ) {
        let vault = vault ?? .shared
        guard let correlationId = json["correlation_id"] as? String else {
            DevLogger.shared.error("🔑 provider_key_store missing correlation_id", context: "websocket")
            return
        }
        guard let name = json["name"] as? String, !name.isEmpty,
              let value = json["value"] as? String, !value.isEmpty else {
            sendResult(correlationId: correlationId, ok: false, error: "bad_request", send: send)
            return
        }
        do {
            try vault.update { $0.providerKeys[name] = value }
            DevLogger.shared.info("🔑 Stored provider key \(name)", context: "websocket")
            sendResult(correlationId: correlationId, ok: true, error: nil, send: send)
        } catch CredentialVaultError.unreadable {
            sendResult(correlationId: correlationId, ok: false, error: "vault_unreadable", send: send)
        } catch {
            DevLogger.shared.error("🔑 Could not store provider key \(name)", context: "websocket")
            sendResult(correlationId: correlationId, ok: false, error: "write_failed", send: send)
        }
    }

    /// Removes one provider key from the vault and acknowledges with `provider_key_result`. Removing a key that is not stored succeeds.
    @MainActor
    static func handleKeyDelete(
        _ json: [String: Any],
        vault: CredentialVault? = nil,
        send: (String) -> Void
    ) {
        let vault = vault ?? .shared
        guard let correlationId = json["correlation_id"] as? String else {
            DevLogger.shared.error("🔑 provider_key_delete missing correlation_id", context: "websocket")
            return
        }
        guard let name = json["name"] as? String, !name.isEmpty else {
            sendResult(correlationId: correlationId, ok: false, error: "bad_request", send: send)
            return
        }
        guard let contents = vault.load() else {
            sendResult(correlationId: correlationId, ok: false, error: "vault_unreadable", send: send)
            return
        }
        guard contents.providerKeys[name] != nil else {
            sendResult(correlationId: correlationId, ok: true, error: nil, send: send)
            return
        }
        do {
            try vault.update { $0.providerKeys.removeValue(forKey: name) }
            DevLogger.shared.info("🔑 Removed provider key \(name)", context: "websocket")
            sendResult(correlationId: correlationId, ok: true, error: nil, send: send)
        } catch {
            DevLogger.shared.error("🔑 Could not remove provider key \(name)", context: "websocket")
            sendResult(correlationId: correlationId, ok: false, error: "write_failed", send: send)
        }
    }

    private static func sendResult(correlationId: String, ok: Bool, error: String?, send: (String) -> Void) {
        var response: [String: Any] = [
            "type": "provider_key_result",
            "correlation_id": correlationId,
            "ok": ok
        ]
        if let error {
            response["error"] = error
        }
        sendJSON(response, send: send)
    }

    private static func sendJSON(_ payload: [String: Any], send: (String) -> Void) {
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let text = String(data: data, encoding: .utf8) else {
            return
        }
        send(text)
    }
}

extension WebSocketService {
    /// Sends a text frame on the open socket without the `isConnected` guard `sendMessage` applies, because the backend asks for provider keys before the connected flag has been set.
    @MainActor
    func sendOnOpenSocket(_ text: String) {
        webSocket?.send(.string(text)) { error in
            if let error {
                DevLogger.shared.error("🔑 Could not send a provider-key reply: \(error.localizedDescription)", context: "websocket")
            }
        }
    }
}
