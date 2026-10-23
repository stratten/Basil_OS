import Foundation
import SwiftUI
import Combine

/// ViewModel for the Account Settings tab
///
/// This ViewModel uses lazy loading for authentication-related data to avoid
/// triggering keychain access prompts when users just want to change their
/// API key preference. Auth data is only loaded when:
/// - User explicitly requests it (signs in, views payment/usage)
/// - The user selects Basil Cloud and eligibility needs checking
@MainActor
class AccountSettingsViewModel: ObservableObject {
    // MARK: - Published Properties
    
    // Authentication - loaded lazily to avoid keychain prompts
    @Published var isAuthenticated = false
    @Published var userEmail = ""
    @Published var subscriptionStatus = ""
    @Published private(set) var hasLoadedAuthState = false
    
    // Payment
    @Published var hasPaymentMethod = false
    @Published var cardBrand = ""
    @Published var cardLast4 = ""
    @Published var cardExpMonth = 0
    @Published var cardExpYear = 0
    
    // Usage
    @Published var isLoadingUsage = false
    @Published var currentPeriodStart: Date = Date()
    @Published var currentPeriodEnd: Date = Date()
    @Published var totalCostUsd: Double = 0
    @Published var totalInputTokens: Int = 0
    @Published var totalOutputTokens: Int = 0
    @Published var usageByModel: [String: ModelUsage] = [:]
    
    // API Key Preference - loaded immediately (no keychain access needed)
    @Published var apiKeyPreference: APIKeyPreference = .useLocalModels
    
    // Sheet States
    @Published var showingLoginSheet = false
    @Published var showingSignupSheet = false
    @Published var showingPaymentSetup = false
    @Published var showingDeleteConfirmation = false

    /// Set when `deleteAccount()` throws (e.g. blocked by an
    /// outstanding balance). The legacy SwiftUI tab surfaces this
    /// inline since account deletion is irreversible and the user
    /// needs the exact reason, not a generic failure toast.
    @Published var deleteAccountErrorMessage: String?
    
    // MARK: - Computed Properties
    
    var currentPeriodFormatted: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "MMM d"
        // Use UTC timezone for formatting since the backend sends calendar dates in UTC
        // This prevents timezone offsets from shifting the displayed dates
        formatter.timeZone = TimeZone(identifier: "UTC")
        return "\(formatter.string(from: currentPeriodStart)) - \(formatter.string(from: currentPeriodEnd))"
    }
    
    var totalCostFormatted: String {
        return String(format: "$%.2f", totalCostUsd)
    }
    
    var totalTokensFormatted: String {
        let total = totalInputTokens + totalOutputTokens
        if total >= 1_000_000 {
            return String(format: "%.1fM", Double(total) / 1_000_000)
        } else if total >= 1000 {
            return String(format: "%.1fK", Double(total) / 1000)
        }
        return "\(total)"
    }
    
    var cardBrandFormatted: String {
        return cardBrand.prefix(1).uppercased() + cardBrand.dropFirst().lowercased()
    }
    
    var cardExpirationFormatted: String {
        return "\(cardExpMonth)/\(cardExpYear)"
    }
    
    var basilCloudSelected: Bool {
        apiKeyPreference.isBasilCloudAlias
    }
    
    var basilCloudEligible: Bool {
        hasLoadedAuthState && isAuthenticated && hasPaymentMethod
    }

    var basilCloudBadge: String {
        if !hasLoadedAuthState {
            return "Account required"
        }
        if basilCloudEligible {
            return "Billing ready"
        }
        return "Setup required"
    }
    
    var basilCloudDescription: String {
        if !hasLoadedAuthState {
            return "Sign in and add payment to use Basil Cloud."
        }
        if !isAuthenticated {
            return "Sign in to continue with Basil Cloud."
        }
        if !hasPaymentMethod {
            return "Add a payment method to continue with Basil Cloud."
        }
        return "Cloud AI access through your Basil account, with usage billed to your account."
    }
    
    // MARK: - Private Properties
    
    private let authClient = AuthClient()
    private var cancellables = Set<AnyCancellable>()
    
    // MARK: - Initialization
    
    init() {
        // Load preference immediately - this doesn't require keychain access
        loadPreferenceOnly()
        observePreferenceChanges()
        // NOTE: Auth state is NOT loaded here to avoid keychain prompts.
        // Call loadAuthStateIfNeeded() when auth-related features are accessed.
    }
    
    // MARK: - Preference Observation
    
    private func observePreferenceChanges() {
        // Observe API key preference changes from the manager
        APIKeyPreferenceManager.shared.$preference
            .receive(on: DispatchQueue.main)
            .sink { [weak self] newPreference in
                self?.apiKeyPreference = newPreference
            }
            .store(in: &cancellables)
    }
    
    // MARK: - Public Methods
    
    /// Loads all data including auth state. Call this when the user actively
    /// interacts with auth-related features (sign in, payment, usage, etc.)
    func loadData() async {
        await loadAuthStateIfNeeded()
        
        if isAuthenticated {
            await loadPaymentMethod()
            await loadUsage()
        }
    }
    
    /// Loads auth state from AuthService. This WILL trigger keychain access.
    /// Call this only when the user needs auth-related features.
    func loadAuthStateIfNeeded() async {
        if !hasLoadedAuthState {
            hasLoadedAuthState = true
            observeAuthServiceChanges()
        }
        loadFromAuthService()
    }
    
    func signOut() async {
        await AuthService.shared.logout()
        loadFromAuthService()
    }
    
    func setAPIKeyPreference(_ preference: APIKeyPreference) {
        apiKeyPreference = preference
        // Use APIKeyPreferenceManager directly for decoupled preference management
        APIKeyPreferenceManager.shared.setPreference(preference)
        
        // Selecting Basil Cloud requires account and payment eligibility.
        if preference.isBasilCloudAlias {
            Task {
                await loadAuthStateIfNeeded()
            }
        }
    }
    
    func selectBasilCloudAccess() async {
        setAPIKeyPreference(.useBasilCloud)
        await loadAuthStateIfNeeded()
        
        if !isAuthenticated {
            showingLoginSheet = true
            return
        }
        
        if !hasPaymentMethod {
            showingPaymentSetup = true
            return
        }
    }
    
    /// Permanently deletes the account. Throws
    /// `AuthError.accountDeletionBlocked` (with the server's exact
    /// reason, e.g. an outstanding balance) or any other `AuthError` on
    /// failure -- callers must surface the message, since a silent
    /// failure here would look like nothing happened when a real,
    /// user-actionable block occurred.
    func deleteAccount() async throws {
        deleteAccountErrorMessage = nil
        do {
            try await AuthService.shared.deleteAccount()
            loadFromAuthService()
        } catch {
            deleteAccountErrorMessage = error.localizedDescription
            throw error
        }
    }
    
    // MARK: - Private Methods
    
    /// Start observing AuthService state changes so the view model updates
    /// reactively when OAuth completes (or any other auth state change occurs).
    /// Only called after the first explicit auth state load to avoid triggering
    /// keychain access prematurely.
    private func observeAuthServiceChanges() {
        AuthService.shared.objectWillChange
            .debounce(for: .milliseconds(100), scheduler: DispatchQueue.main)
            .sink { [weak self] _ in
                Task { @MainActor [weak self] in
                    guard let self = self else { return }
                    let wasAuthenticated = self.isAuthenticated
                    self.loadFromAuthService()
                    if self.isAuthenticated && !wasAuthenticated {
                        await self.loadPaymentMethod()
                        await self.loadUsage()
                    }
                }
            }
            .store(in: &cancellables)
    }
    
    /// Loads only the API key preference - no keychain access required
    private func loadPreferenceOnly() {
        apiKeyPreference = APIKeyPreferenceManager.shared.preference
    }
    
    /// Loads auth state from AuthService. This triggers keychain access.
    private func loadFromAuthService() {
        let authService = AuthService.shared
        isAuthenticated = authService.isAuthenticated
        hasPaymentMethod = authService.hasPaymentMethod
        // Get preference from APIKeyPreferenceManager for decoupled access
        apiKeyPreference = APIKeyPreferenceManager.shared.preference
        
        if let user = authService.currentUser {
            userEmail = user.email
            subscriptionStatus = user.subscriptionStatus
        } else {
            userEmail = ""
            subscriptionStatus = ""
        }
    }
    
    private func loadPaymentMethod() async {
        guard let token = AuthService.shared.getAccessToken() else { return }
        
        do {
            let paymentMethod = try await authClient.getPaymentMethod(accessToken: token)
            hasPaymentMethod = paymentMethod.hasPaymentMethod
            cardBrand = paymentMethod.cardBrand ?? ""
            cardLast4 = paymentMethod.cardLast4 ?? ""
            cardExpMonth = paymentMethod.cardExpMonth ?? 0
            cardExpYear = paymentMethod.cardExpYear ?? 0
        } catch {
            print("Failed to load payment method: \(error)")
        }
    }
    
    private func loadUsage() async {
        guard let token = AuthService.shared.getAccessToken() else { return }
        
        isLoadingUsage = true
        
        do {
            let usage = try await authClient.getCurrentUsage(accessToken: token)
            currentPeriodStart = usage.periodStart
            currentPeriodEnd = usage.periodEnd
            totalCostUsd = usage.totalCostUsd
            totalInputTokens = usage.totalInputTokens
            totalOutputTokens = usage.totalOutputTokens
            usageByModel = usage.usageByModel
        } catch {
            print("Failed to load usage: \(error)")
        }
        
        isLoadingUsage = false
    }
    
}

