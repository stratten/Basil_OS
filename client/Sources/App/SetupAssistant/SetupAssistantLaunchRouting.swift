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

/// What the first-run flow opens first.
enum SetupAssistantFirstRunStep: Equatable {
    /// Permissions are missing: show the permissions window, which continues into the Setup Assistant once all are granted.
    case showPermissions
    /// Permissions are in place, or this is the validation profile: open the Setup Assistant directly.
    case showAssistant
}

enum SetupAssistantFirstRunGate {
    static func nextStep(allRequiredPermissionsGranted: Bool, isValidationProfile: Bool) -> SetupAssistantFirstRunStep {
        if isValidationProfile { return .showAssistant }
        return allRequiredPermissionsGranted ? .showAssistant : .showPermissions
    }
}

enum SetupAssistantLaunchRouting {
    static func route(backendHasCompletedOnboarding: Bool?, pendingSetupAssistant: Bool) -> SetupAssistantLaunchRoute {
        if backendHasCompletedOnboarding == true { return .nothing }
        if pendingSetupAssistant { return .permissionsCheckOnly }
        return .primarySetupFlow
    }
}
