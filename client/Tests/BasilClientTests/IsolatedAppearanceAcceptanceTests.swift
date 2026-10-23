import WebKit
import XCTest
@testable import BasilClient

/// Proves that a single isolated, synthetic appearance-update fixture (never
/// touching real UserDefaults, real backend state, or the operator's actual
/// preferences) results in two independently-instantiated, real WebView host
/// classes both receiving the same, correct new theme payload -- the
/// "multiple already-open renderers stay in sync from one broadcast" claim
/// Package 8's roadmap entry asks this test to cover. See this file's
/// planning companion (Package 8, Companion 11) for why this test verifies
/// the wire-format payload via a recorder-stub page rather than the real
/// bundled React app: the test target's `Package.swift` declares no
/// `resources:`, so the real per-panel web asset folders are not available
/// inside `swift test`.
@MainActor
final class IsolatedAppearanceAcceptanceTests: XCTestCase {
    /// A minimal page defining the exact global callback name each real
    /// production page defines, recording the received JSON into a page-level
    /// variable this test reads back via a value-returning `evaluateJavaScript`
    /// call instead of relying on the real (unavailable in this test target)
    /// bundled React app to render anything.
    private static func recorderStubHTML(namespace: String) -> String {
        """
        <!DOCTYPE html>
        <html><head></head><body>
        <script>
          window.__basilLastThemePayload = null;
          window.\(namespace) = {
            onInit: function(payload) { window.__basilLastThemePayload = payload.theme; },
            onThemeChanged: function(theme, fonts) { window.__basilLastThemePayload = theme; },
          };
        </script>
        </body></html>
        """
    }

    /// Kept alive for the duration of each test method so the WKWebView's
    /// `navigationDelegate` (a weak/unowned reference on WKWebView) does not
    /// get deallocated between `loadRecorderStub` and the navigation actually
    /// finishing.
    private var retainedNavigationDelegates: [LoadCompletionNavigationDelegate] = []

    override func tearDown() {
        retainedNavigationDelegates.removeAll()
        super.tearDown()
    }

    private func loadRecorderStub(into webView: WKWebView, namespace: String) {
        let expectation = expectation(description: "recorder stub loaded")
        let delegate = LoadCompletionNavigationDelegate(onFinish: { expectation.fulfill() })
        retainedNavigationDelegates.append(delegate)
        webView.navigationDelegate = delegate
        webView.loadHTMLString(Self.recorderStubHTML(namespace: namespace), baseURL: nil)
        wait(for: [expectation], timeout: 5)
    }

    private func readLastThemePayload(from webView: WKWebView) -> [String: Any]? {
        var result: [String: Any]?
        let expectation = expectation(description: "read back recorded payload")
        webView.evaluateJavaScript("JSON.stringify(window.__basilLastThemePayload)") { value, _ in
            if let jsonString = value as? String,
               let data = jsonString.data(using: .utf8),
               let decoded = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                result = decoded
            }
            expectation.fulfill()
        }
        wait(for: [expectation], timeout: 5)
        return result
    }

    func testTwoIndependentlyRegisteredHostsReceiveTheSameIsolatedAppearanceUpdate() {
        let modelDownloadHost = ModelDownloadMiniPanelWebView()
        let meetingDetectedHost = MeetingDetectedMiniPanelWebView()
        defer { modelDownloadHost.tearDown() }

        loadRecorderStub(into: modelDownloadHost.webView, namespace: "basilModelDownloadPanel")
        loadRecorderStub(into: meetingDetectedHost.webView, namespace: "basilMeetingDetectedPanel")

        // Isolated, synthetic fixture: never touches real UserDefaults, the
        // real backend, or the operator's actual saved appearance settings.
        // This is the exact mechanism AppearanceRefreshCoordinatorTests already
        // exercises for its own in-memory-cache assertions.
        WebSocketService.shared.handleAppearanceUpdated([
            "revision": AestheticSystem.currentAppearanceRevision + 1,
            "appearance_settings": [
                "background_color_red": 0.043,
                "background_color_green": 0.122,
                "background_color_blue": 0.059,
                "primary_color_red": 1.0,
                "primary_color_green": 0.42,
                "primary_color_blue": 0.208,
                "preferred_font": "Menlo",
            ],
        ])

        modelDownloadHost.sendThemeChanged()
        meetingDetectedHost.sendThemeChanged()

        let modelDownloadPayload = readLastThemePayload(from: modelDownloadHost.webView)
        let meetingDetectedPayload = readLastThemePayload(from: meetingDetectedHost.webView)

        XCTAssertNotNil(modelDownloadPayload, "Model Download host did not record a theme payload")
        XCTAssertNotNil(meetingDetectedPayload, "Meeting Detected host did not record a theme payload")

        let expectedPrimaryHex = AestheticWebPayload.colorToHex(AestheticSystem.Colors.primary)
        XCTAssertEqual(modelDownloadPayload?["primary"] as? String, expectedPrimaryHex)
        XCTAssertEqual(meetingDetectedPayload?["primary"] as? String, expectedPrimaryHex)

        let expectedBackgroundHex = AestheticWebPayload.colorToHex(AestheticSystem.Colors.backgroundPrimary)
        XCTAssertEqual(modelDownloadPayload?["backgroundPrimary"] as? String, expectedBackgroundHex)
        XCTAssertEqual(meetingDetectedPayload?["backgroundPrimary"] as? String, expectedBackgroundHex)
    }
}
