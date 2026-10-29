import Foundation
import Security
import os

/// Keychain storage for remote MCP connection tokens (Gmail, GitHub, Linear, custom servers), independent of the Basil account session.
///
/// These tokens used to be reached through ``AuthService``, whose first construction immediately reads the Basil account item to restore the Basil Cloud session. That meant adding, using, or removing a Gmail connection could ask macOS for permission to read an unrelated Basil account credential. This store never reads the account.
///
/// All connections' tokens live in the shared ``CredentialVault`` (the same single Keychain item that holds the account session and the provider API keys), so a build whose code signature changed, such as every ad-hoc development build, is asked for Keychain access once per launch instead of once per secret. Earlier versions stored two items per connection (``com.basil.mcpToken.<id>`` and ``com.basil.mcpRefreshToken.<id>``). A connection missing from the vault is read from those items once, copied into the vault, and the old items are removed, so existing tokens keep working without the user signing in again.
///
/// Reads are cached in memory by the vault: the first request in a process reads the vault once, and every later request is answered from memory. ``store`` writes through to the vault and its cache, and ``delete`` removes the connection from both, so the cache cannot drift from the Keychain. If the vault exists but cannot be read (for example the user chose Deny), the store falls back to the per-connection items for that request and never overwrites the vault, so a denied prompt cannot erase the other secrets.
@MainActor
final class MCPTokenStore {
    typealias ReadItem = (_ key: String) -> String?
    typealias WriteItem = (_ key: String, _ value: String) throws -> Void
    typealias DeleteItem = (_ key: String) -> Void
    /// Whether an item exists, answered from its attributes alone so it never needs permission to read the secret.
    typealias ItemExists = (_ key: String) -> Bool

    static let shared = MCPTokenStore(
        vault: CredentialVault.shared,
        readItem: LoginKeychainItems.read,
        writeItem: LoginKeychainItems.write,
        deleteItem: LoginKeychainItems.delete
    )

    private typealias Entry = CredentialVault.ConnectionEntry

    private let vault: CredentialVault
    private let readItem: ReadItem
    private let writeItem: WriteItem
    private let deleteItem: DeleteItem

    init(
        vault: CredentialVault,
        readItem: @escaping ReadItem,
        writeItem: @escaping WriteItem,
        deleteItem: @escaping DeleteItem
    ) {
        self.vault = vault
        self.readItem = readItem
        self.writeItem = writeItem
        self.deleteItem = deleteItem
    }

    /// Builds a store with its own vault over the same closures. Tests use this form; the app uses ``shared``.
    convenience init(
        readItem: @escaping ReadItem,
        writeItem: @escaping WriteItem,
        deleteItem: @escaping DeleteItem,
        itemExists: @escaping ItemExists = { _ in false }
    ) {
        self.init(
            vault: CredentialVault(
                vaultKey: BasilRuntimeProfile.credentialKey("com.basil.mcpTokenVault"),
                readItem: readItem,
                writeItem: writeItem,
                itemExists: itemExists
            ),
            readItem: readItem,
            writeItem: writeItem,
            deleteItem: deleteItem
        )
    }

    private func accessTokenKey(connectionId: String) -> String {
        BasilRuntimeProfile.credentialKey("com.basil.mcpToken.\(connectionId)")
    }

    private func refreshTokenKey(connectionId: String) -> String {
        BasilRuntimeProfile.credentialKey("com.basil.mcpRefreshToken.\(connectionId)")
    }

    private func deleteLegacyItems(connectionId: String) {
        deleteItem(accessTokenKey(connectionId: connectionId))
        deleteItem(refreshTokenKey(connectionId: connectionId))
    }

    /// Copies a connection's earlier per-connection items into the vault, then removes them. If the vault cannot be saved the tokens are still returned and the old items are kept, so nothing is lost.
    private func migrateLegacyItems(connectionId: String) -> Entry? {
        let access = readItem(accessTokenKey(connectionId: connectionId))
        let refresh = readItem(refreshTokenKey(connectionId: connectionId))
        guard access != nil || refresh != nil else { return nil }
        let entry = Entry(access: access, refresh: refresh)
        do {
            try vault.update { $0.connections[connectionId] = entry }
            deleteLegacyItems(connectionId: connectionId)
        } catch {
            LoginKeychainItems.logWarning("Could not move connection tokens into the vault; keeping the earlier items")
            vault.remember { $0.connections[connectionId] = entry }
        }
        return entry
    }

    /// The connection's entry from memory, the vault, or the earlier per-connection items, in that order. Nil when the connection has no stored tokens or the vault is unreadable and the earlier items are gone.
    private func entry(connectionId: String) -> Entry? {
        guard let current = vault.load() else {
            return Entry(
                access: readItem(accessTokenKey(connectionId: connectionId)),
                refresh: readItem(refreshTokenKey(connectionId: connectionId))
            )
        }
        if let known = current.connections[connectionId] { return known }
        return migrateLegacyItems(connectionId: connectionId)
    }

    /// Persists the access token for a connection. A supplied refresh token is stored alongside it. Passing nil leaves any existing refresh token in place unless `replacingRefreshToken` is true, in which case the old refresh token is removed so it cannot outlive the grant it belonged to.
    func store(
        connectionId: String,
        accessToken: String,
        refreshToken: String? = nil,
        replacingRefreshToken: Bool = false
    ) throws {
        guard vault.load() != nil else {
            try storeInLegacyItems(
                connectionId: connectionId,
                accessToken: accessToken,
                refreshToken: refreshToken,
                replacingRefreshToken: replacingRefreshToken
            )
            return
        }
        var refresh = refreshToken
        if refresh == nil, !replacingRefreshToken {
            refresh = entry(connectionId: connectionId)?.refresh
        }
        let updated = Entry(access: accessToken, refresh: refresh)
        try vault.update { $0.connections[connectionId] = updated }
        deleteLegacyItems(connectionId: connectionId)
    }

    /// Used only while the vault is unreadable: writes the earlier per-connection items so the new token is not lost, and leaves the vault untouched.
    private func storeInLegacyItems(
        connectionId: String,
        accessToken: String,
        refreshToken: String?,
        replacingRefreshToken: Bool
    ) throws {
        try writeItem(accessTokenKey(connectionId: connectionId), accessToken)
        if let refreshToken {
            try writeItem(refreshTokenKey(connectionId: connectionId), refreshToken)
        } else if replacingRefreshToken {
            deleteItem(refreshTokenKey(connectionId: connectionId))
        }
    }

    /// The access token for a connection. Once the vault has been read, this does not touch the Keychain, so it cannot present a macOS password prompt.
    func accessToken(connectionId: String) -> String? {
        entry(connectionId: connectionId)?.access
    }

    /// The refresh token for a connection, if one is stored. Once the vault has been read, this does not touch the Keychain.
    func refreshToken(connectionId: String) -> String? {
        entry(connectionId: connectionId)?.refresh
    }

    /// Whether the next access-token request can be answered from memory without touching the Keychain.
    func hasCachedAccessToken(connectionId: String) -> Bool {
        vault.cachedContents?.connections[connectionId] != nil
    }

    /// Whether the next refresh-token request can be answered from memory without touching the Keychain. A connection known to have no refresh token is also answered from memory.
    func hasCachedRefreshToken(connectionId: String) -> Bool {
        vault.cachedContents?.connections[connectionId] != nil
    }

    /// Removes a connection's tokens when the user deletes it. If the vault cannot be read, its entry is left in place; connection ids are never reused, so the stale entry is never served.
    func delete(connectionId: String) {
        if vault.load()?.connections[connectionId] != nil {
            do {
                try vault.update { $0.connections.removeValue(forKey: connectionId) }
            } catch {
                LoginKeychainItems.logWarning("Could not remove a deleted connection's tokens from the vault")
            }
        }
        deleteLegacyItems(connectionId: connectionId)
    }
}

enum MCPTokenStoreError: LocalizedError {
    case keychainWriteFailed(status: OSStatus)

    var errorDescription: String? {
        switch self {
        case .keychainWriteFailed(let status):
            return "Failed to save the connection token to the Keychain (status \(status))."
        }
    }
}

/// Generic-password items in the login Keychain, addressed by account name only, with the same attributes ``AuthService`` uses so both see the same items.
enum LoginKeychainItems {
    private static let logger = Logger(subsystem: "com.basil.client", category: "MCPTokenStore")

    static func write(key: String, value: String) throws {
        guard let data = value.data(using: .utf8) else { return }
        delete(key: key)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        ]
        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else {
            logger.error("Keychain SecItemAdd failed (status=\(status)) for key=\(key, privacy: .public)")
            throw MCPTokenStoreError.keychainWriteFailed(status: status)
        }
    }

    static func read(key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data, let value = String(data: data, encoding: .utf8) else {
            if status != errSecItemNotFound {
                logger.error("Keychain read failed (status=\(status)) for key=\(key, privacy: .public)")
                return nil
            }
            return migrateProtectedItem(key: key)
        }
        return value
    }

    /// Whether a login-Keychain item exists. Only attributes are requested, never the secret, so this does not need permission to read the item.
    static func exists(key: String) -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecReturnAttributes as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: AnyObject?
        return SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess
    }

    static func logWarning(_ message: String) {
        logger.warning("\(message, privacy: .public)")
    }

    static func delete(key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key
        ]
        SecItemDelete(query as CFDictionary)
        var protectedQuery = query
        protectedQuery[kSecUseDataProtectionKeychain as String] = true
        SecItemDelete(protectedQuery as CFDictionary)
    }

    /// Earlier code could leave an item in the data protection Keychain with a user-presence requirement. If one exists, read it once, rewrite it to the login Keychain, and let the rewrite remove the protected copy so later launches read silently.
    private static func migrateProtectedItem(key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecUseDataProtectionKeychain as String: true,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let value = String(data: data, encoding: .utf8) else {
            return nil
        }
        do {
            try write(key: key, value: value)
        } catch {
            logger.warning("Could not migrate protected Keychain item for key=\(key, privacy: .public)")
        }
        return value
    }
}
