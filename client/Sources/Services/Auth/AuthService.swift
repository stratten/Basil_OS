import Foundation
import Security
import os

/// Service for managing user authentication state
@MainActor
final class AuthService: ObservableObject {
    // MARK: - Singleton
    static let shared = AuthService()
    
    // MARK: - Published State
    @Published private(set) var state: AuthState = .unauthenticated
    @Published private(set) var currentUser: AuthUser?
    @Published private(set) var hasPaymentMethod: Bool = false
    
    /// API key preference - delegates to APIKeyPreferenceManager for decoupled management.
    /// This property is kept for backwards compatibility but preference management
    /// is now handled by APIKeyPreferenceManager.
    var apiKeyPreference: APIKeyPreference {
        APIKeyPreferenceManager.shared.preference
    }
    
    // MARK: - Properties
    private let logger = Logger(subsystem: "com.basil.client", category: "AuthService")
    private let authClient = AuthClient()
    private let apiClient = APIClient.shared
    
    // Flag to prevent clearing auth state during OAuth flow
    private var oauthFlowInProgress = false
    

    // Per-connection MCP tokens (Gmail, GitHub, Linear, custom) live in ``MCPTokenStore``, not here, so working with a connection never constructs this service and never reads the Basil account from the Keychain.

    // The access token, refresh token, and payment flag share one Keychain item so reading the account asks macOS for permission once, not once per value. The three keys below are the older one-item-per-value layout, read only to migrate it.
    private lazy var vaultAccountItems = VaultAccountItems(
        vault: CredentialVault.shared,
        accountKey: BasilRuntimeProfile.credentialKey("com.basil.account"),
        readItem: { [unowned self] key in self.getFromKeychain(key: key) },
        writeItem: { [unowned self] key, value in try self.saveToKeychain(key: key, value: value) },
        deleteItem: { [unowned self] key in self.deleteFromKeychain(key: key) }
    )

    private lazy var credentialStore = AccountCredentialStore(
        accountKey: BasilRuntimeProfile.credentialKey("com.basil.account"),
        legacyAccessTokenKey: BasilRuntimeProfile.credentialKey("com.basil.accessToken"),
        legacyRefreshTokenKey: BasilRuntimeProfile.credentialKey("com.basil.refreshToken"),
        legacyPaymentMethodKey: BasilRuntimeProfile.credentialKey("com.basil.hasPaymentMethod"),
        readItem: { [unowned self] key in self.vaultAccountItems.read(key: key) },
        writeItem: { [unowned self] key, value in try self.vaultAccountItems.write(key: key, value: value) },
        deleteItem: { [unowned self] key in self.vaultAccountItems.delete(key: key) }
    )
    
    var isAuthenticated: Bool {
        if case .authenticated = state { return true }
        return false
    }
    
    var canUseAppKeys: Bool {
        isAuthenticated && hasPaymentMethod && apiKeyPreference.isBasilCloudAlias
    }
    
    // MARK: - Initialization
    private init() {
        // Try to restore session on init
        Task {
            await restoreSession()
        }
    }
    
    // MARK: - Public Methods
    
    /// Register with email and password
    func register(email: String, password: String) async throws {
        state = .loading
        
        do {
            let tokens = try await authClient.register(email: email, password: password)
            try saveTokens(tokens)
            
            let user = try await authClient.getCurrentUser(accessToken: tokens.accessToken)
            currentUser = user
            hasPaymentMethod = user.hasPaymentMethod
            saveHasPaymentMethod(user.hasPaymentMethod)
            state = .authenticated(user: user, tokens: tokens)
            
            // Sync with backend
            await syncAuthSettingsToBackend()
            
            logger.info("User registered: \(email)")
        } catch {
            state = .unauthenticated
            await syncAuthSettingsToBackend()
            throw error
        }
    }
    
    /// Login with email and password
    func login(email: String, password: String) async throws {
        state = .loading
        
        do {
            let tokens = try await authClient.login(email: email, password: password)
            try saveTokens(tokens)
            
            let user = try await authClient.getCurrentUser(accessToken: tokens.accessToken)
            currentUser = user
            hasPaymentMethod = user.hasPaymentMethod
            saveHasPaymentMethod(user.hasPaymentMethod)
            state = .authenticated(user: user, tokens: tokens)
            
            // Sync with backend
            await syncAuthSettingsToBackend()
            
            logger.info("User logged in: \(email)")
        } catch {
            state = .unauthenticated
            await syncAuthSettingsToBackend()
            throw error
        }
    }
    
    /// Get Google OAuth URL
    func getGoogleAuthURL() async throws -> URL {
        // Mark OAuth flow as in progress to prevent token clearing
        oauthFlowInProgress = true
        logger.info("🔐 OAuth flow started")
        
        // Safety timeout: Clear OAuth flag after 5 minutes in case flow never completes
        Task {
            try? await Task.sleep(nanoseconds: 5 * 60 * 1_000_000_000) // 5 minutes
            if oauthFlowInProgress {
                logger.warning("🔐 OAuth flow timed out - clearing flag")
                oauthFlowInProgress = false
            }
        }
        
        let response = try await authClient.startGoogleAuth()
        guard let url = URL(string: response.authorizationUrl) else {
            oauthFlowInProgress = false
            throw AuthError.networkError("Invalid authorization URL")
        }
        return url
    }
    
    /// Complete Google OAuth with authorization code
    func completeGoogleAuth(code: String) async throws {
        state = .loading
        
        do {
            let tokens = try await authClient.completeGoogleAuth(code: code)
            try saveTokens(tokens)
            
            let user = try await authClient.getCurrentUser(accessToken: tokens.accessToken)
            currentUser = user
            hasPaymentMethod = user.hasPaymentMethod
            saveHasPaymentMethod(user.hasPaymentMethod)
            state = .authenticated(user: user, tokens: tokens)
            
            // Sync with backend
            await syncAuthSettingsToBackend()
            
            logger.info("User logged in via Google: \(user.email)")
        } catch {
            state = .unauthenticated
            await syncAuthSettingsToBackend()
            throw error
        }
    }
    
    /// Complete OAuth with tokens received from URL callback
    func completeOAuthWithTokens(_ tokens: AuthTokens) async throws {
        NSLog("🚨🚨🚨 [AuthService] completeOAuthWithTokens CALLED")
        state = .loading
        logger.info("🔐 Completing OAuth with tokens from URL callback")
        
        do {
            NSLog("🚨🚨🚨 [AuthService] About to save tokens to keychain")
            try saveTokens(tokens)
            NSLog("🚨🚨🚨 [AuthService] Tokens saved to keychain successfully")
            logger.info("🔐 Tokens saved to keychain")
            
            NSLog("🚨🚨🚨 [AuthService] Fetching user with access token")
            let user = try await authClient.getCurrentUser(accessToken: tokens.accessToken)
            NSLog("🚨🚨🚨 [AuthService] User fetched: %@", user.email)
            currentUser = user
            hasPaymentMethod = user.hasPaymentMethod
            saveHasPaymentMethod(user.hasPaymentMethod)
            state = .authenticated(user: user, tokens: tokens)
            
            // Clear OAuth flow flag before syncing
            oauthFlowInProgress = false
            NSLog("🚨🚨🚨 [AuthService] OAuth flow flag cleared")
            logger.info("🔐 OAuth flow marked as complete")
            
            // Sync with backend
            NSLog("🚨🚨🚨 [AuthService] Syncing to backend")
            await syncAuthSettingsToBackend()
            NSLog("🚨🚨🚨 [AuthService] Backend sync complete")
            
            logger.info("OAuth completed via URL callback for: \(user.email)")
            NSLog("🚨🚨🚨 [AuthService] completeOAuthWithTokens COMPLETED SUCCESSFULLY")
        } catch {
            NSLog("🚨🚨🚨 [AuthService] ERROR in completeOAuthWithTokens: %@", error.localizedDescription)
            // Clear OAuth flow flag on error too
            oauthFlowInProgress = false
            state = .unauthenticated
            await syncAuthSettingsToBackend()
            throw error
        }
    }
    
    /// Logout
    func logout() async {
        if let token = getAccessToken() {
            try? await authClient.logout(accessToken: token)
        }
        
        clearTokens()
        currentUser = nil
        hasPaymentMethod = false
        state = .unauthenticated
        
        // Sync with backend
        await syncAuthSettingsToBackend()
        
        logger.info("User logged out")
    }

    /// Permanently deletes the authenticated user's account via
    /// `BasilAuthService` (which runs final billing first). Unlike
    /// `logout()`, this only clears local session state on a confirmed
    /// server-side success -- a thrown `AuthError.accountDeletionBlocked`
    /// (or any other error) leaves the session untouched so the caller's
    /// UI can surface the exact reason and let the user retry or resolve
    /// the block (e.g. pay an outstanding balance) without being logged out.
    func deleteAccount() async throws {
        guard let token = getAccessToken() else {
            throw AuthError.notAuthenticated
        }

        _ = try await authClient.deleteAccount(accessToken: token)

        clearTokens()
        currentUser = nil
        hasPaymentMethod = false
        state = .unauthenticated

        await syncAuthSettingsToBackend()

        logger.info("User account deleted")
    }
    
    /// Refresh user data
    func refreshUserData() async throws {
        guard let token = getAccessToken() else {
            throw AuthError.notAuthenticated
        }
        
        let user = try await authClient.getCurrentUser(accessToken: token)
        currentUser = user
        hasPaymentMethod = user.hasPaymentMethod
        saveHasPaymentMethod(user.hasPaymentMethod)
        
        if case .authenticated(_, let tokens) = state {
            state = .authenticated(user: user, tokens: tokens)
        }
        
        // Sync with backend
        await syncAuthSettingsToBackend()
    }
    
    /// Set API key preference - delegates to APIKeyPreferenceManager.
    /// This method is kept for backwards compatibility. New code should use
    /// APIKeyPreferenceManager.shared.setPreference() directly.
    func setAPIKeyPreference(_ preference: APIKeyPreference) {
        // Delegate to the preference manager which handles backend sync.
        APIKeyPreferenceManager.shared.setPreference(preference)
    }
    
    /// Get the current access token. The first call reads the Keychain once for the whole account; every later call is answered from memory.
    func getAccessToken() -> String? {
        credentialStore.load()?.accessToken
    }
    
    // MARK: - Backend Settings Sync
    
    /// Sync auth settings to backend (api_key_preference, is_authenticated, user_email)
    private func syncAuthSettingsToBackend() async {
        NSLog("🚨🚨🚨 [AuthService] syncAuthSettingsToBackend called, oauthFlowInProgress: %@", oauthFlowInProgress ? "YES" : "NO")
        // Skip syncing if OAuth flow is in progress to prevent clearing tokens
        if oauthFlowInProgress {
            NSLog("🚨🚨🚨 [AuthService] SKIPPING backend sync - OAuth flow in progress")
            logger.info("🔐 Skipping backend sync - OAuth flow in progress")
            return
        }
        
        NSLog("🚨🚨🚨 [AuthService] Syncing auth settings: authenticated=%@, email=%@", isAuthenticated ? "YES" : "NO", currentUser?.email ?? "nil")
        do {
            let settings = AuthSettingsUpdate(
                apiKeyPreference: apiKeyPreference.rawValue,
                isAuthenticated: isAuthenticated,
                userEmail: currentUser?.email
            )
            try await apiClient.updateAuthSettings(settings)
            
            // Also sync access token to Python backend for auth proxy routing
            if isAuthenticated, let token = getAccessToken() {
                try await apiClient.setAuthToken(token)
                logger.debug("Access token synced to Python backend")
            } else {
                try await apiClient.clearAuthToken()
                logger.debug("Access token cleared from Python backend")
            }
            
            logger.debug("Auth settings synced to backend")
        } catch {
            logger.warning("Failed to sync auth settings to backend: \(error.localizedDescription)")
        }
    }
    
    /// Load auth settings from backend - delegates to APIKeyPreferenceManager
    private func loadAuthSettingsFromBackend() async {
        // API key preference is now managed by APIKeyPreferenceManager
        // which loads from backend on its own init. We just ensure it's loaded.
        await APIKeyPreferenceManager.shared.loadPreference()
        logger.debug("Auth settings loaded via APIKeyPreferenceManager")
    }
    
    // MARK: - Private Methods
    
    private func restoreSession() async {
        // First, load API key preference from backend settings
        await loadAuthSettingsFromBackend()
        
        // Check for stored tokens
        guard let stored = credentialStore.load() else {
            state = .unauthenticated
            hasPaymentMethod = false
            return
        }
        let accessToken = stored.accessToken
        let refreshToken = stored.refreshToken
        
        state = .loading
        
        // Try to get user with existing token
        do {
            let user = try await authClient.getCurrentUser(accessToken: accessToken)
            currentUser = user
            hasPaymentMethod = user.hasPaymentMethod
            saveHasPaymentMethod(user.hasPaymentMethod)
            
            let tokens = AuthTokens(
                accessToken: accessToken,
                refreshToken: refreshToken,
                tokenType: "bearer",
                expiresIn: 900 // Assume 15 min, will refresh if needed
            )
            state = .authenticated(user: user, tokens: tokens)
            
            // Sync auth state to backend
            await syncAuthSettingsToBackend()
            
            logger.info("Session restored for: \(user.email)")
        } catch {
            // Token might be expired, try to refresh
            do {
                let newTokens = try await authClient.refreshToken(refreshToken: refreshToken)
                try saveTokens(newTokens)
                
                let user = try await authClient.getCurrentUser(accessToken: newTokens.accessToken)
                currentUser = user
                hasPaymentMethod = user.hasPaymentMethod
                saveHasPaymentMethod(user.hasPaymentMethod)
                state = .authenticated(user: user, tokens: newTokens)
                
                // Sync auth state to backend
                await syncAuthSettingsToBackend()
                
                logger.info("Session refreshed for: \(user.email)")
            } catch {
                // Failed to refresh, clear and go to unauthenticated
                clearTokens()
                state = .unauthenticated
                await syncAuthSettingsToBackend()
                logger.warning("Failed to restore session: \(error.localizedDescription)")
            }
        }
    }
    
    private func saveTokens(_ tokens: AuthTokens) throws {
        try credentialStore.save(
            accessToken: tokens.accessToken,
            refreshToken: tokens.refreshToken,
            hasPaymentMethod: hasPaymentMethod
        )
    }
    
    private func saveHasPaymentMethod(_ value: Bool) {
        credentialStore.updateHasPaymentMethod(value)
    }
    
    private func clearTokens() {
        credentialStore.clear()
    }
    
    // MARK: - Keychain Helpers
    
    func saveToKeychain(key: String, value: String) throws {
        let data = value.data(using: .utf8)!

        // Items live in the login keychain with no per-read user-presence requirement. macOS trusts the creating app by its code-signing designated requirement, so a Developer ID build (stable team ID and bundle ID) reads silently across launches and updates. Ad-hoc development builds get a new designated requirement on every rebuild, so macOS asks once per item after each rebuild.
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        ]

        deleteFromKeychain(key: key)

        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else {
            logger.error("Failed to save to keychain: \(status)")
            DevLogger.shared.error(
                "Keychain SecItemAdd failed (status=\(status)) for key=\(key)",
                context: "AuthService.saveToKeychain"
            )
            throw AuthError.networkError("Failed to save to keychain")
        }
    }
    
    func getFromKeychain(key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        
        guard status == errSecSuccess,
              let data = result as? Data,
              let value = String(data: data, encoding: .utf8) else {
            if status != errSecItemNotFound {
                logger.error("Keychain read failed: \(status)")
                return nil
            }
            return migrateUserPresenceProtectedKeychainItem(key: key)
        }
        
        return value
    }
    
    func deleteFromKeychain(key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key
        ]
        SecItemDelete(query as CFDictionary)
        var protectedQuery = query
        protectedQuery[kSecUseDataProtectionKeychain as String] = true
        SecItemDelete(protectedQuery as CFDictionary)
    }

}

