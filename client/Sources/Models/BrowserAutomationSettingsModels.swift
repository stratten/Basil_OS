import Foundation

enum BrowserSensitiveFillPolicy: String, Codable, CaseIterable, Identifiable {
    case never
    case askEveryTime = "ask_every_time"
    case approvedDomains = "approved_domains"

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .never:
            return "Never fill sensitive fields"
        case .askEveryTime:
            return "Ask every time"
        case .approvedDomains:
            return "Allow for approved domains"
        }
    }
}

enum BrowserForegroundControlPolicy: String, Codable, CaseIterable, Identifiable {
    case backgroundOnly = "background_only"
    case askBeforeForeground = "ask_before_foreground"
    case allowForegroundWhenNeeded = "allow_foreground_when_needed"

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .backgroundOnly:
            return "Background / DOM only"
        case .askBeforeForeground:
            return "Ask before foreground takeover"
        case .allowForegroundWhenNeeded:
            return "Allow foreground takeover when needed"
        }
    }

    var description: String {
        switch self {
        case .backgroundOnly:
            return "Basil will stop and ask you to fix permissions instead of using keyboard or mouse control."
        case .askBeforeForeground:
            return "Basil may use DOM automation freely, but asks before taking over the visible browser."
        case .allowForegroundWhenNeeded:
            return "Basil may activate the browser and use keyboard or mouse automation when needed."
        }
    }
}

enum BrowserAutomationSessionMode: String, Codable, CaseIterable, Identifiable {
    case userBrowser = "user_browser"
    case basilAutomationBrowser = "basil_automation_browser"

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .userBrowser:
            return "Existing browser session"
        case .basilAutomationBrowser:
            return "Basil Automation Browser"
        }
    }

    var description: String {
        switch self {
        case .userBrowser:
            return "Use Safari, Chrome, or Edge and the user's current logged-in browser session."
        case .basilAutomationBrowser:
            return "Use the future Basil-owned background browser profile when available."
        }
    }
}

enum BrowserPreferredUserBrowser: String, Codable, CaseIterable, Identifiable {
    case systemDefault = "system_default"
    case chrome
    case edge
    case safari

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .systemDefault:
            return "System default"
        case .chrome:
            return "Chrome"
        case .edge:
            return "Edge"
        case .safari:
            return "Safari"
        }
    }

    var description: String {
        switch self {
        case .systemDefault:
            return "Use the macOS default browser when Basil needs a user-browser automation session."
        case .chrome:
            return "Prefer Google Chrome for Basil user-browser automation."
        case .edge:
            return "Prefer Microsoft Edge for Basil user-browser automation."
        case .safari:
            return "Prefer Safari for Basil user-browser automation."
        }
    }
}

struct BrowserDomainApproval: Codable, Identifiable {
    let domain: String
    let createdAt: String?
    let lastUsed: String?
    let useCount: Int
    let allowSensitiveFill: Bool

    var id: String { domain }

    enum CodingKeys: String, CodingKey {
        case domain
        case createdAt = "created_at"
        case lastUsed = "last_used"
        case useCount = "use_count"
        case allowSensitiveFill = "allow_sensitive_fill"
    }
}

struct BrowserAutomationSettings: Codable {
    var sensitiveFillPolicy: BrowserSensitiveFillPolicy
    var foregroundControlPolicy: BrowserForegroundControlPolicy
    var defaultSessionMode: BrowserAutomationSessionMode
    var preferredUserBrowser: BrowserPreferredUserBrowser
    var approvedSensitiveFillDomains: [BrowserDomainApproval]
    var showActionHighlights: Bool
    var recordBrowserActionTrace: Bool
    var allowVisualFallback: Bool

    enum CodingKeys: String, CodingKey {
        case sensitiveFillPolicy = "sensitive_fill_policy"
        case foregroundControlPolicy = "foreground_control_policy"
        case defaultSessionMode = "default_session_mode"
        case preferredUserBrowser = "preferred_user_browser"
        case approvedSensitiveFillDomains = "approved_sensitive_fill_domains"
        case showActionHighlights = "show_action_highlights"
        case recordBrowserActionTrace = "record_browser_action_trace"
        case allowVisualFallback = "allow_visual_fallback"
    }
}

struct UpdateBrowserAutomationSettingsRequest: Codable {
    var sensitiveFillPolicy: BrowserSensitiveFillPolicy? = nil
    var foregroundControlPolicy: BrowserForegroundControlPolicy? = nil
    var defaultSessionMode: BrowserAutomationSessionMode? = nil
    var preferredUserBrowser: BrowserPreferredUserBrowser? = nil
    var showActionHighlights: Bool? = nil
    var recordBrowserActionTrace: Bool? = nil
    var allowVisualFallback: Bool? = nil

    enum CodingKeys: String, CodingKey {
        case sensitiveFillPolicy = "sensitive_fill_policy"
        case foregroundControlPolicy = "foreground_control_policy"
        case defaultSessionMode = "default_session_mode"
        case preferredUserBrowser = "preferred_user_browser"
        case showActionHighlights = "show_action_highlights"
        case recordBrowserActionTrace = "record_browser_action_trace"
        case allowVisualFallback = "allow_visual_fallback"
    }
}

struct BrowserAutomationSettingsGetResponse: Codable {
    let settings: BrowserAutomationSettings
}

struct BrowserAutomationSettingsUpdateResponse: Codable {
    let status: String
    let updatedSettings: BrowserAutomationSettings
    let message: String?

    enum CodingKeys: String, CodingKey {
        case status
        case updatedSettings = "updated_settings"
        case message
    }
}

