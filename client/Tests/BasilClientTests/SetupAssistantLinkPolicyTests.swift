import Foundation
import XCTest
@testable import BasilClient

final class SetupAssistantLinkPolicyTests: XCTestCase {
    func testWebAndMailLinksOpenExternally() {
        XCTAssertEqual(
            SetupAssistantLinkPolicy.externalURLToOpen(for: URL(string: "https://platform.openai.com/api-keys")),
            URL(string: "https://platform.openai.com/api-keys")
        )
        XCTAssertNotNil(SetupAssistantLinkPolicy.externalURLToOpen(for: URL(string: "http://example.com")))
        XCTAssertNotNil(SetupAssistantLinkPolicy.externalURLToOpen(for: URL(string: "mailto:help@example.com")))
    }

    func testLocalFilesCustomSchemesAndMissingURLsNeverOpen() {
        XCTAssertNil(SetupAssistantLinkPolicy.externalURLToOpen(for: URL(string: "file:///Applications/Calculator.app")))
        XCTAssertNil(SetupAssistantLinkPolicy.externalURLToOpen(for: URL(string: "basil://mcp/slack_oauth_callback")))
        XCTAssertNil(SetupAssistantLinkPolicy.externalURLToOpen(for: URL(string: "javascript:alert(1)")))
        XCTAssertNil(SetupAssistantLinkPolicy.externalURLToOpen(for: nil))
    }
}
