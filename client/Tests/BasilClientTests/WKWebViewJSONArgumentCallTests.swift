import AppKit
import WebKit
import XCTest
@testable import BasilClient

@MainActor
final class WKWebViewJSONArgumentCallTests: XCTestCase {
    private final class FailureRecorder {
        var messages: [String] = []
    }

    private var retainedDelegate: LoadCompletionNavigationDelegate?

    func testJSONLiteralCoversFragmentsAndRejectsInvalidValues() {
        XCTAssertEqual(WKWebView.jsonLiteral(for: "a\"b"), "\"a\\\"b\"")
        XCTAssertEqual(WKWebView.jsonLiteral(for: 3), "3")
        XCTAssertEqual(WKWebView.jsonLiteral(for: true), "true")
        XCTAssertEqual(WKWebView.jsonLiteral(for: NSNull()), "null")
        XCTAssertEqual(WKWebView.jsonLiteral(for: ["k": 1]), "{\"k\":1}")
        XCTAssertNil(WKWebView.jsonLiteral(for: Double.nan))
        XCTAssertNil(WKWebView.jsonLiteral(for: Date()))
        XCTAssertNil(WKWebView.jsonLiteral(for: [1: "non-string key"]))
    }

    func testDeliversEveryArgumentInOrderWithItsOwnType() async throws {
        let webView = try await loadedWebView()

        webView.callBasilFunction(
            "window.basilTestSurface.onCall",
            args: [
                ["theme": ["primary": "#003087"]],
                "text with \" quote and </script> and \u{2028}",
                42,
                true,
                NSNull(),
            ],
            logTag: "TEST_SURFACE",
            logContext: "WKWebViewJSONArgumentCallTests"
        )

        let received = try await receivedCalls(in: webView, expecting: 1)
        XCTAssertEqual(received.count, 1)
        let args = try XCTUnwrap(received[0] as? [Any])
        XCTAssertEqual(args.count, 5)
        XCTAssertEqual(((args[0] as? [String: Any])?["theme"] as? [String: Any])?["primary"] as? String, "#003087")
        XCTAssertEqual(args[1] as? String, "text with \" quote and </script> and \u{2028}")
        XCTAssertEqual(args[2] as? Int, 42)
        XCTAssertEqual(args[3] as? Bool, true)
        XCTAssertTrue(args[4] is NSNull)
    }

    func testInvalidArgumentDropsTheWholeCallAndReportsIt() async throws {
        let webView = try await loadedWebView()
        let recorder = FailureRecorder()

        webView.callBasilFunction(
            "window.basilTestSurface.onCall",
            args: ["first", Double.nan, "third"],
            logTag: "TEST_SURFACE",
            logContext: "WKWebViewJSONArgumentCallTests",
            onFailure: { recorder.messages.append($0) }
        )
        webView.callBasilFunction(
            "window.basilTestSurface.onCall",
            args: ["after"],
            logTag: "TEST_SURFACE",
            logContext: "WKWebViewJSONArgumentCallTests"
        )

        let received = try await receivedCalls(in: webView, expecting: 1)
        XCTAssertEqual(received.count, 1, "Only the valid call should reach the page")
        XCTAssertEqual((received[0] as? [Any])?.first as? String, "after")
        XCTAssertEqual(recorder.messages.count, 1)
        XCTAssertTrue(recorder.messages[0].contains("argument 1"), recorder.messages[0])
        XCTAssertTrue(recorder.messages[0].contains("window.basilTestSurface.onCall"), recorder.messages[0])
    }

    func testGuardedExpressionIsSilentWhenTheSurfaceIsMissingAndCallsItWhenPresent() async throws {
        let webView = try await loadedWebView()
        let recorder = FailureRecorder()

        webView.callBasilFunction(
            "window.notInstalled && window.notInstalled.onCall",
            args: [["ignored": true]],
            logTag: "TEST_SURFACE",
            logContext: "WKWebViewJSONArgumentCallTests",
            onFailure: { recorder.messages.append($0) }
        )
        webView.callBasilFunction(
            "window.basilTestSurface && window.basilTestSurface.onCall",
            args: [["present": true]],
            logTag: "TEST_SURFACE",
            logContext: "WKWebViewJSONArgumentCallTests",
            onFailure: { recorder.messages.append($0) }
        )

        let received = try await receivedCalls(in: webView, expecting: 1)
        XCTAssertEqual(received.count, 1)
        XCTAssertEqual(((received[0] as? [Any])?.first as? [String: Any])?["present"] as? Bool, true)
        XCTAssertTrue(recorder.messages.isEmpty, "A guarded expression for a missing surface is not a failure")
    }

    func testPageErrorIsReportedThroughOnFailure() async throws {
        let webView = try await loadedWebView()
        let failureReported = expectation(description: "page error reported")
        var reported: String?

        webView.callBasilFunction(
            "window.noSuchSurface.onCall",
            args: [["x": 1]],
            logTag: "TEST_SURFACE",
            logContext: "WKWebViewJSONArgumentCallTests",
            onFailure: { message in
                reported = message
                failureReported.fulfill()
            }
        )

        await fulfillment(of: [failureReported], timeout: 5)
        XCTAssertTrue(reported?.contains("window.noSuchSurface.onCall") == true, reported ?? "nil")
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
            window.basilTestSurface = { onCall: function () { window.received.push(Array.prototype.slice.call(arguments)); } };
            </script>
            """,
            baseURL: nil
        )
        await fulfillment(of: [pageLoaded], timeout: 5)
        return webView
    }

    private func receivedCalls(in webView: WKWebView, expecting count: Int) async throws -> [Any] {
        for _ in 0..<100 {
            let json = try await webView.evaluateJavaScript("JSON.stringify(window.received)") as? String ?? "[]"
            let parsed = try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [Any] ?? []
            if parsed.count >= count {
                return parsed
            }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTFail("Timed out waiting for \(count) call(s)")
        return []
    }
}
