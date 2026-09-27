import Foundation
import SwiftUI

/// Manages trial quota balance and exhaustion state.
/// Tracks remaining balance from server responses and shows exhaustion alert when depleted.
@MainActor
final class TrialExhaustionManager: ObservableObject {
    // MARK: - Singleton
    static let shared = TrialExhaustionManager()
    
    // MARK: - Constants
    
    /// Default trial allowance in USD when not yet fetched from server.
    static let defaultAllowanceUsd: Double = 1.00
    
    // MARK: - Published State
    
    /// Whether to show the exhaustion alert. Observed by the app-level view.
    @Published var isShowingExhaustionAlert = false
    
    /// Remaining trial balance in USD. Updated from server responses.
    /// Supports up to 6 decimal places for OpenRouter precision.
    @Published private(set) var remainingBalanceUsd: Double = 1.00
    
    /// Total trial limit in USD for this key. Updated from server responses.
    /// Supports custom limits per key (e.g., $5.00 for promotional keys).
    @Published private(set) var limitUsd: Double = 1.00
    
    /// Whether the trial quota has been exhausted.
    var isTrialExhausted: Bool {
        remainingBalanceUsd <= 0.000001  // Account for floating point precision
    }
    
    /// Remaining balance formatted for display (e.g., "$0.75" or "$0.001234").
    var remainingBalanceFormatted: String {
        formatUsd(remainingBalanceUsd)
    }
    
    /// Limit formatted for display (e.g., "$1.00" or "$5.00").
    var limitFormatted: String {
        formatUsd(limitUsd)
    }
    
    /// Usage percentage (0.0 to 1.0) for progress indicators.
    var usagePercentage: Double {
        guard limitUsd > 0 else { return 0 }
        let used = limitUsd - remainingBalanceUsd
        return min(1.0, max(0.0, used / limitUsd))
    }
    
    // MARK: - Private Properties
    private let remainingBalanceKey = "trial_remaining_balance_usd"
    private let limitKey = "trial_limit_usd"
    private let lastUpdatedKey = "trial_balance_last_updated"
    
    // MARK: - Initialization
    private init() {
        // Restore balance from UserDefaults
        if BasilRuntimeProfile.userDefaults.object(forKey: remainingBalanceKey) != nil {
            remainingBalanceUsd = BasilRuntimeProfile.userDefaults.double(forKey: remainingBalanceKey)
            limitUsd = BasilRuntimeProfile.userDefaults.double(forKey: limitKey)
            // Ensure limit is at least the default if somehow zero
            if limitUsd <= 0 {
                limitUsd = Self.defaultAllowanceUsd
            }
        } else {
            // First launch - start with default balance
            remainingBalanceUsd = Self.defaultAllowanceUsd
            limitUsd = Self.defaultAllowanceUsd
        }
    }
    
    // MARK: - Formatting Helpers
    
    /// Format USD amount for display. Uses 2 decimals for values >= $0.01, up to 6 for smaller.
    private func formatUsd(_ amount: Double) -> String {
        if amount >= 0.01 || amount == 0 {
            return String(format: "$%.2f", amount)
        } else {
            // For very small amounts, show more precision
            let formatted = String(format: "$%.6f", amount)
            // Trim trailing zeros
            return formatted.replacingOccurrences(of: "0+$", with: "", options: .regularExpression)
        }
    }
    
    // MARK: - Pre-flight Check
    
    /// Call this BEFORE making an unauthenticated Basil Cloud request.
    /// Returns true if the request can proceed, false if included credit is exhausted.
    /// If exhausted, automatically shows the alert.
    func canMakeTrialRequest() -> Bool {
        // If user is authenticated, they're not on trial - always allow
        if AuthService.shared.isAuthenticated {
            return true
        }
        
        // Check if using Basil Cloud or a legacy trial/app-keys alias.
        guard AuthService.shared.apiKeyPreference.isBasilCloudAlias else {
            return true
        }
        
        // If trial is exhausted, show alert and block
        if isTrialExhausted {
            showExhaustionAlert()
            return false
        }
        
        return true
    }
    
    // MARK: - Balance Updates from Server
    
    /// Update remaining balance from server response.
    /// Call this after every successful trial request.
    /// - Parameters:
    ///   - remainingUsd: Remaining balance in USD (up to 6 decimal places).
    ///   - limit: Optional new limit in USD. If nil, keeps existing limit.
    func updateBalance(remainingUsd: Double, limit: Double? = nil) {
        let previousBalance = remainingBalanceUsd
        remainingBalanceUsd = max(0, remainingUsd)
        
        if let newLimit = limit, newLimit > 0 {
            limitUsd = newLimit
            BasilRuntimeProfile.userDefaults.set(limitUsd, forKey: limitKey)
        }
        
        // Persist to UserDefaults
        BasilRuntimeProfile.userDefaults.set(remainingBalanceUsd, forKey: remainingBalanceKey)
        BasilRuntimeProfile.userDefaults.set(Date().timeIntervalSince1970, forKey: lastUpdatedKey)
        
        #if DEBUG
        DevLogger.shared.info("🎫 Trial balance updated: $\(String(format: "%.6f", previousBalance)) → $\(String(format: "%.6f", remainingBalanceUsd)) (limit: $\(String(format: "%.2f", limitUsd)))", context: "TrialExhaustionManager")
        #endif
        
        // Check if just became exhausted
        if remainingBalanceUsd <= 0.000001 && previousBalance > 0.000001 {
            showExhaustionAlert()
        }
    }
    
    /// Update balance from server response headers.
    /// - Parameters:
    ///   - remainingHeader: Value of X-Trial-Remaining-Usd header.
    ///   - limitHeader: Optional value of X-Trial-Limit-Usd header.
    func updateBalanceFromHeaders(remaining remainingHeader: String?, limit limitHeader: String? = nil) {
        guard let remainingHeader = remainingHeader,
              let remainingUsd = Double(remainingHeader) else {
            return
        }
        let limitUsd = limitHeader.flatMap { Double($0) }
        updateBalance(remainingUsd: remainingUsd, limit: limitUsd)
    }
    
    // MARK: - Server Error Handling
    
    /// Handle a 402 error from the server.
    /// Returns true if this was a trial exhaustion.
    @discardableResult
    func handleServerError(statusCode: Int, message: String?) -> Bool {
        guard statusCode == 402 else { return false }
        
        // Check if this is trial exhaustion vs payment method required
        let lowercasedMessage = message?.lowercased() ?? ""
        let isTrialError = lowercasedMessage.contains("trial") ||
                          lowercasedMessage.contains("included") ||
                          lowercasedMessage.contains("credit exhausted") ||
                          !AuthService.shared.isAuthenticated
        
        if isTrialError {
            updateBalance(remainingUsd: 0)
            showExhaustionAlert()
            return true
        }
        
        return false
    }
    
    // MARK: - Alert Control
    
    /// Show the exhaustion alert as a standalone window. Delegates to
    /// `TrialExhaustionWindowController`, which hosts the React panel (with
    /// a native SwiftUI fallback if the bundle fails to load).
    func showExhaustionAlert() {
        isShowingExhaustionAlert = true
        TrialExhaustionWindowController.shared.show()

        #if DEBUG
        DevLogger.shared.info("🎫 Trial exhaustion alert window displayed", context: "TrialExhaustionManager")
        #endif
    }
    
    /// Dismiss the exhaustion alert.
    func dismissAlert() {
        isShowingExhaustionAlert = false
        TrialExhaustionWindowController.shared.dismiss()
    }
    
    // MARK: - State Management
    
    /// Reset trial balance to full (for testing or after key regeneration).
    func resetBalance() {
        remainingBalanceUsd = limitUsd
        BasilRuntimeProfile.userDefaults.set(remainingBalanceUsd, forKey: remainingBalanceKey)
        BasilRuntimeProfile.userDefaults.removeObject(forKey: lastUpdatedKey)
        
        #if DEBUG
        DevLogger.shared.info("🎫 Trial balance reset to $\(String(format: "%.2f", limitUsd))", context: "TrialExhaustionManager")
        #endif
    }
    
    /// Clear all trial state. Called when user signs up or switches away from trial.
    func clearTrialState() {
        BasilRuntimeProfile.userDefaults.removeObject(forKey: remainingBalanceKey)
        BasilRuntimeProfile.userDefaults.removeObject(forKey: limitKey)
        BasilRuntimeProfile.userDefaults.removeObject(forKey: lastUpdatedKey)
        remainingBalanceUsd = Self.defaultAllowanceUsd
        limitUsd = Self.defaultAllowanceUsd
        isShowingExhaustionAlert = false
        
        #if DEBUG
        DevLogger.shared.info("🎫 Trial state cleared.", context: "TrialExhaustionManager")
        #endif
    }
}
