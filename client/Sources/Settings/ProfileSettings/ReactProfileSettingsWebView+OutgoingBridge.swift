import Foundation

@MainActor
protocol ReactProfileSettingsBridgeOutput: AnyObject {
    func sendInit(profile: UserProfile)
    func sendSnapshot(profile: UserProfile)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactProfileSettingsWebView: ReactProfileSettingsBridgeOutput {
    func sendInit(profile: UserProfile) {
        var event = fieldsEvent(type: "init", profile: profile)
        event["protocolVersion"] = 1
        callJS("window.basilProfileSettings && window.basilProfileSettings.onEvent", args: event)
    }

    func sendSnapshot(profile: UserProfile) {
        let event = fieldsEvent(type: "snapshot", profile: profile)
        callJS("window.basilProfileSettings && window.basilProfileSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = [
            "type": "intentResult",
            "requestId": requestId,
            "status": status,
        ]
        if let message {
            event["message"] = message
        }
        callJS("window.basilProfileSettings && window.basilProfileSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = [
            "type": "loadError",
            "message": message,
        ]
        callJS("window.basilProfileSettings && window.basilProfileSettings.onEvent", args: event)
    }

    private func fieldsEvent(type: String, profile: UserProfile) -> [String: Any] {
        let fields: [String: Any] = [
            "fullName": profile.full_name ?? NSNull(),
            "preferredName": profile.preferred_name ?? NSNull(),
            "email": profile.email ?? NSNull(),
            "jobTitle": profile.job_title ?? NSNull(),
            "companyName": profile.company_name ?? NSNull(),
            "industry": profile.industry ?? NSNull(),
            "formality": profile.default_formality?.rawValue ?? NSNull(),
            "tone": profile.default_tone?.rawValue ?? NSNull(),
            "customInstructions": profile.custom_instructions ?? NSNull(),
        ]
        return [
            "type": type,
            "profile": fields,
        ]
    }
}
