import Foundation
import Security

@MainActor
extension AuthService {
    /// Earlier code tried to store items in the data protection keychain with a Touch ID or password requirement on every read. If such an item exists, read it once (this read may prompt), rewrite it to the login keychain through ``saveToKeychain(key:value:)``, and let that save remove the protected copy so later launches read silently.
    func migrateUserPresenceProtectedKeychainItem(key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecUseDataProtectionKeychain as String: true,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess,
              let data = result as? Data,
              let value = String(data: data, encoding: .utf8) else {
            return nil
        }

        do {
            try saveToKeychain(key: key, value: value)
        } catch {
            DevLogger.shared.warning(
                "Could not migrate protected Keychain item for key=\(key): \(error.localizedDescription)",
                context: "AuthService.migrateUserPresenceProtectedKeychainItem"
            )
        }
        return value
    }
}
