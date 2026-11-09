import XCTest
import Foundation
@testable import BasilClient

final class ProblemReportServiceTests: XCTestCase {
    private func result(issueUrl: String) -> ProblemReportResult {
        ProblemReportResult(bundlePath: "/tmp/Basil_Problem_Report.zip", issueUrl: issueUrl, logExcerptAvailable: true)
    }

    func testAnIssueLinkForThisRepositoryIsOpenedAsGiven() {
        let link = "https://github.com/stratten/Basil_OS/issues/new?title=Problem&body=Details"

        XCTAssertEqual(ProblemReportService.issueURLToOpen(from: result(issueUrl: link)).absoluteString, link)
    }

    func testAnyOtherLinkFallsBackToThePlainNewIssuePage() {
        let rejected = [
            "http://github.com/stratten/Basil_OS/issues/new",
            "https://example.com/stratten/Basil_OS/issues/new",
            "https://github.com/someone/else/issues/new",
            "https://github.com/stratten/Basil_OS/pulls",
            "file:///etc/passwd",
            "not a url",
            ""
        ]
        for link in rejected {
            XCTAssertEqual(
                ProblemReportService.issueURLToOpen(from: result(issueUrl: link)),
                ProblemReportService.fallbackIssueURL,
                "Expected a fallback for \(link)"
            )
        }
    }

    func testAMissingResultFallsBackToThePlainNewIssuePage() {
        XCTAssertEqual(ProblemReportService.issueURLToOpen(from: nil), ProblemReportService.fallbackIssueURL)
    }

    func testTheRequestCarriesVersionsAndTrimsAnEmptyDetailToNil() {
        let body = ProblemReportService.makeRequestBody(source: "status_bar", detail: "  \n ")

        XCTAssertEqual(body.source, "status_bar")
        XCTAssertNil(body.detail)
        XCTAssertTrue(body.macosVersion.hasPrefix("macOS "))
        XCTAssertFalse(body.appVersion.isEmpty)
    }

    func testTheRequestKeepsATrimmedDetail() {
        let body = ProblemReportService.makeRequestBody(source: "setup_assistant", detail: "  llama_decode returned -3 \n")

        XCTAssertEqual(body.detail, "llama_decode returned -3")
    }

    func testTheRequestEncodesToTheBackendFieldNames() throws {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let data = try encoder.encode(ProblemReportRequestBody(source: "app", detail: nil, appVersion: "1.0.2", macosVersion: "macOS 26.1.0"))
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])

        XCTAssertEqual(json["app_version"] as? String, "1.0.2")
        XCTAssertEqual(json["macos_version"] as? String, "macOS 26.1.0")
        XCTAssertEqual(json["source"] as? String, "app")
    }

    func testTheResultDecodesTheBackendFieldNames() throws {
        let data = Data("""
        {"bundle_path": "/tmp/a.zip", "issue_url": "https://github.com/stratten/Basil_OS/issues/new", "log_excerpt_available": false}
        """.utf8)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        let decoded = try decoder.decode(ProblemReportResult.self, from: data)

        XCTAssertEqual(decoded.bundlePath, "/tmp/a.zip")
        XCTAssertFalse(decoded.logExcerptAvailable)
    }
}
