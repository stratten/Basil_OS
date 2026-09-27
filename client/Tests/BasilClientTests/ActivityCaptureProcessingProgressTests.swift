import XCTest
@testable import BasilClient

final class ActivityCaptureProcessingProgressTests: XCTestCase {
    func testDecodesParallelActivityProcessingProgress() throws {
        let data = Data(
            """
            {
              "active": true,
              "total": 500,
              "processed": 24,
              "succeeded": 24,
              "failed": 0,
              "remaining": 476,
              "eta_seconds": 550.0,
              "cancel_requested": false,
              "started_at": "2026-08-19T18:00:00",
              "last_error": null,
              "max_records": 0,
              "analysis_concurrency": 8,
              "processing_strategy": "api_parallel"
            }
            """.utf8
        )

        let progress = try JSONDecoder().decode(
            ActivityProcessingProgressResponse.self,
            from: data
        )

        XCTAssertEqual(progress.analysisConcurrency, 8)
        XCTAssertEqual(progress.processingStrategy, "api_parallel")
    }

    func testDecodesLegacyActivityProcessingProgressWithoutPolicyFields() throws {
        let data = Data(
            """
            {
              "active": false,
              "total": 0,
              "processed": 0,
              "succeeded": 0,
              "failed": 0,
              "remaining": 0,
              "eta_seconds": null,
              "cancel_requested": false,
              "started_at": null,
              "last_error": null,
              "max_records": 0
            }
            """.utf8
        )

        let progress = try JSONDecoder().decode(
            ActivityProcessingProgressResponse.self,
            from: data
        )

        XCTAssertNil(progress.analysisConcurrency)
        XCTAssertNil(progress.processingStrategy)
    }
}
