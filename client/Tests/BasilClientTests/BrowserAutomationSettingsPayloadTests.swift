import XCTest
@testable import BasilClient

final class BrowserAutomationSettingsPayloadTests: XCTestCase {
    func testMapsSettingsFieldsToCamelCaseKeysWithRawEnumValues() {
        let settings = BrowserAutomationSettings(
            sensitiveFillPolicy: .askEveryTime,
            foregroundControlPolicy: .askBeforeForeground,
            defaultSessionMode: .userBrowser,
            preferredUserBrowser: .chrome,
            approvedSensitiveFillDomains: [],
            showActionHighlights: true,
            recordBrowserActionTrace: false,
            allowVisualFallback: true
        )
        let payload = BrowserAutomationSettingsPayloadBuilder.makeSettingsPayload(settings: settings)
        XCTAssertEqual(payload["sensitiveFillPolicy"] as? String, "ask_every_time")
        XCTAssertEqual(payload["foregroundControlPolicy"] as? String, "ask_before_foreground")
        XCTAssertEqual(payload["defaultSessionMode"] as? String, "user_browser")
        XCTAssertEqual(payload["preferredUserBrowser"] as? String, "chrome")
        XCTAssertEqual(payload["showActionHighlights"] as? Bool, true)
        XCTAssertEqual(payload["recordBrowserActionTrace"] as? Bool, false)
        XCTAssertEqual((payload["approvedSensitiveFillDomains"] as? [[String: Any]])?.count, 0)
    }

    func testDomainApprovalFallsBackToEmptyStringsForNilDates() {
        let approval = BrowserDomainApproval(domain: "example.com", createdAt: nil, lastUsed: nil, useCount: 3, allowSensitiveFill: true)
        let payload = BrowserAutomationSettingsPayloadBuilder.makeDomainApprovalPayload(approval)
        XCTAssertEqual(payload["domain"] as? String, "example.com")
        XCTAssertEqual(payload["createdAt"] as? String, "")
        XCTAssertEqual(payload["lastUsed"] as? String, "")
        XCTAssertEqual(payload["useCount"] as? Int, 3)
        XCTAssertEqual(payload["allowSensitiveFill"] as? Bool, true)
    }

    func testDomainApprovalPreservesNonNilDates() {
        let approval = BrowserDomainApproval(domain: "bank.com", createdAt: "2026-01-01T00:00:00Z", lastUsed: "2026-02-01T00:00:00Z", useCount: 1, allowSensitiveFill: false)
        let payload = BrowserAutomationSettingsPayloadBuilder.makeDomainApprovalPayload(approval)
        XCTAssertEqual(payload["createdAt"] as? String, "2026-01-01T00:00:00Z")
        XCTAssertEqual(payload["lastUsed"] as? String, "2026-02-01T00:00:00Z")
    }
}
