import Foundation

enum BrowserAutomationSettingsPayloadBuilder {
    static func makeSettingsPayload(settings: BrowserAutomationSettings) -> [String: Any] {
        [
            "sensitiveFillPolicy": settings.sensitiveFillPolicy.rawValue,
            "foregroundControlPolicy": settings.foregroundControlPolicy.rawValue,
            "defaultSessionMode": settings.defaultSessionMode.rawValue,
            "preferredUserBrowser": settings.preferredUserBrowser.rawValue,
            "approvedSensitiveFillDomains": settings.approvedSensitiveFillDomains.map(makeDomainApprovalPayload),
            "showActionHighlights": settings.showActionHighlights,
            "recordBrowserActionTrace": settings.recordBrowserActionTrace,
            "allowVisualFallback": settings.allowVisualFallback,
        ]
    }

    static func makeDomainApprovalPayload(_ approval: BrowserDomainApproval) -> [String: Any] {
        [
            "domain": approval.domain,
            "createdAt": approval.createdAt ?? "",
            "lastUsed": approval.lastUsed ?? "",
            "useCount": approval.useCount,
            "allowSensitiveFill": approval.allowSensitiveFill,
        ]
    }
}
