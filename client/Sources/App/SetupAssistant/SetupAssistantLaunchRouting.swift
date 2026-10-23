import Foundation

/// What a launch surfaces when this Mac has no local record of finished setup.
enum SetupAssistantLaunchRoute: Equatable {
    /// Setup was finished; nothing is presented.
    case nothing
    /// Setup was skipped earlier. The resume toast and the Settings Resume card offer it again, so launch only surfaces missing permissions.
    case permissionsCheckOnly
    /// First run, or completion could not be confirmed: open the full Setup Assistant.
    case primarySetupFlow
}

enum SetupAssistantLaunchRouting {
    static func route(backendHasCompletedOnboarding: Bool?, pendingSetupAssistant: Bool) -> SetupAssistantLaunchRoute {
        if backendHasCompletedOnboarding == true { return .nothing }
        if pendingSetupAssistant { return .permissionsCheckOnly }
        return .primarySetupFlow
    }
}
