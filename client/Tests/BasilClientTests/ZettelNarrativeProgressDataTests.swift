import XCTest
@testable import BasilClient

final class ZettelNarrativeProgressDataTests: XCTestCase {
    func testDecodesApiParallelProgress() throws {
        let data = Data(
            """
            {
              "active": true,
              "total": 10,
              "processed": 3,
              "finalized": 3,
              "still_open": 0,
              "failed": 0,
              "remaining": 7,
              "eta_seconds": 42.0,
              "last_error": null,
              "cancelling": false,
              "analysis_concurrency": 8,
              "processing_strategy": "api_parallel"
            }
            """.utf8
        )

        let progress = try JSONDecoder().decode(NarrativeProgressData.self, from: data)

        XCTAssertEqual(progress.analysisConcurrency, 8)
        XCTAssertEqual(progress.processingStrategy, "api_parallel")
        XCTAssertTrue(progress.isApiParallel)
    }

    func testDecodesLegacyProgressWithoutConcurrencyFields() throws {
        let data = Data(
            """
            {
              "active": false,
              "total": 5,
              "processed": 5,
              "finalized": 5,
              "still_open": 0,
              "failed": 0,
              "remaining": 0,
              "eta_seconds": null,
              "last_error": null,
              "cancelling": false
            }
            """.utf8
        )

        let progress = try JSONDecoder().decode(NarrativeProgressData.self, from: data)

        XCTAssertNil(progress.analysisConcurrency)
        XCTAssertNil(progress.processingStrategy)
        XCTAssertFalse(progress.isApiParallel)
    }
}
