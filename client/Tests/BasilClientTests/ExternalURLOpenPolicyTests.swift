import XCTest
@testable import BasilClient

final class ExternalURLOpenPolicyTests: XCTestCase {
    func testPlainHTTPSAddressIsOpened() {
        let url = WebSocketService_MCP.externalURLToOpen(from: ["url": "https://github.com/login/device"])
        XCTAssertEqual(url?.absoluteString, "https://github.com/login/device")
    }

    func testAddressWithQueryIsOpened() {
        let url = WebSocketService_MCP.externalURLToOpen(from: ["url": "https://auth.notion.com/authorize?state=abc&x=1"])
        XCTAssertEqual(url?.host, "auth.notion.com")
    }

    func testOtherSchemesAreIgnored() {
        for raw in ["http://example.com/", "file:///etc/hosts", "basil://mcp/connection_complete", "javascript:alert(1)", "x-apple.systempreferences:", "ssh://host"] {
            XCTAssertNil(WebSocketService_MCP.externalURLToOpen(from: ["url": raw]), raw)
        }
    }

    func testEmbeddedCredentialsAreIgnored() {
        XCTAssertNil(WebSocketService_MCP.externalURLToOpen(from: ["url": "https://user:pw@example.com/"]))
        XCTAssertNil(WebSocketService_MCP.externalURLToOpen(from: ["url": "https://user@example.com/"]))
    }

    func testMissingMalformedOrOversizedAddressesAreIgnored() {
        XCTAssertNil(WebSocketService_MCP.externalURLToOpen(from: [:]))
        XCTAssertNil(WebSocketService_MCP.externalURLToOpen(from: ["url": 42]))
        XCTAssertNil(WebSocketService_MCP.externalURLToOpen(from: ["url": ""]))
        XCTAssertNil(WebSocketService_MCP.externalURLToOpen(from: ["url": "https://"]))
        XCTAssertNil(WebSocketService_MCP.externalURLToOpen(from: ["url": "https://example.com/a b"]))
        XCTAssertNil(WebSocketService_MCP.externalURLToOpen(from: ["url": "https://example.com/" + String(repeating: "a", count: 5000)]))
    }
}
