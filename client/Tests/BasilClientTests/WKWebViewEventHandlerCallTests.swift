import AppKit
import WebKit
import XCTest
@testable import BasilClient

@MainActor
final class WKWebViewEventHandlerCallTests: XCTestCase {
    private var retainedDelegate: LoadCompletionNavigationDelegate?

    func testDeliversOneEventToTheNamedFunctionWithoutEscapingIssues() async throws {
        let webView = try await loadedWebView()
        let event: [String: Any] = [
            "kind": "ping",
            "count": 3,
            "text": "quote \" backslash \\ newline \n angle </script> separator \u{2028}",
            "nested": ["flag": true],
        ]

        webView.callBasilEventHandler(
            "window.basilTestSurface.onEvent",
            event: event,
            logTag: "TEST_SURFACE_WEB",
            logContext: "WKWebViewEventHandlerCallTests"
        )

        let received = try await receivedEvents(in: webView, expecting: 1)
        XCTAssertEqual(received.count, 1)
        XCTAssertEqual(received[0]["kind"] as? String, "ping")
        XCTAssertEqual(received[0]["count"] as? Int, 3)
        XCTAssertEqual(received[0]["text"] as? String, event["text"] as? String)
        XCTAssertEqual((received[0]["nested"] as? [String: Any])?["flag"] as? Bool, true)
    }

    func testDeliversEventsInCallOrder() async throws {
        let webView = try await loadedWebView()

        for index in 0..<3 {
            webView.callBasilEventHandler(
                "window.basilTestSurface.onEvent",
                event: ["index": index],
                logTag: "TEST_SURFACE_WEB",
                logContext: "WKWebViewEventHandlerCallTests"
            )
        }

        let received = try await receivedEvents(in: webView, expecting: 3)
        XCTAssertEqual(received.compactMap { $0["index"] as? Int }, [0, 1, 2])
    }

    func testMissingFunctionDoesNotDisturbLaterCalls() async throws {
        let webView = try await loadedWebView()

        webView.callBasilEventHandler(
            "window.noSuchSurface.onEvent",
            event: ["ignored": true],
            logTag: "TEST_SURFACE_WEB",
            logContext: "WKWebViewEventHandlerCallTests"
        )
        webView.callBasilEventHandler(
            "window.basilTestSurface.onEvent",
            event: ["after": "failure"],
            logTag: "TEST_SURFACE_WEB",
            logContext: "WKWebViewEventHandlerCallTests"
        )

        let received = try await receivedEvents(in: webView, expecting: 1)
        XCTAssertEqual(received.count, 1)
        XCTAssertEqual(received[0]["after"] as? String, "failure")
    }

    private func loadedWebView() async throws -> WKWebView {
        let webView = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        let pageLoaded = expectation(description: "test page loads")
        let delegate = LoadCompletionNavigationDelegate { pageLoaded.fulfill() }
        retainedDelegate = delegate
        webView.navigationDelegate = delegate
        webView.loadHTMLString(
            """
            <script>
            window.received = [];
            window.basilTestSurface = { onEvent: function (event) { window.received.push(event); } };
            </script>
            """,
            baseURL: nil
        )
        await fulfillment(of: [pageLoaded], timeout: 5)
        return webView
    }

    private func receivedEvents(in webView: WKWebView, expecting count: Int) async throws -> [[String: Any]] {
        for _ in 0..<100 {
            let json = try await webView.evaluateJavaScript("JSON.stringify(window.received)") as? String ?? "[]"
            let parsed = try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [[String: Any]] ?? []
            if parsed.count >= count {
                return parsed
            }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTFail("Timed out waiting for \(count) event(s)")
        return []
    }
}
