import AppKit
import Foundation

/// Wires the previously-dead ``"navigateToSettings"`` notification (posted by
/// the trial-exhaustion alert's "Sign Up"/"Continue with Basil Cloud" and
/// "Use Your Own Provider Account" actions) to the Settings window.
///
/// Both actions route to the Account tab: the API-key-preference row (used
/// by "Use Your Own Provider Account") already lives on that tab alongside
/// sign-in/billing, so there is a single destination regardless of which
/// button the user pressed.
extension AppDelegate {
    private static let navigateToSettingsNotificationName = NSNotification.Name("navigateToSettings")

    /// Subscribe the AppDelegate to "navigateToSettings" notifications.
    /// Idempotent — safe to call multiple times.
    @MainActor
    func registerTrialExhaustionNavigateObserver() {
        guard trialExhaustionNavigateObserverToken == nil else { return }
        let token = NotificationCenter.default.addObserver(
            forName: AppDelegate.navigateToSettingsNotificationName,
            object: nil,
            queue: .main
        ) { _ in
            Task { @MainActor in
                SettingsShellWindowController.shared.navigateToTab("account")
            }
        }
        trialExhaustionNavigateObserverToken = token

        #if DEBUG
        DevLogger.shared.info("[TrialExhaustion] AppDelegate observer registered for navigateToSettings", context: "TrialExhaustion")
        #endif
    }
}
