import XCTest
import Foundation
@testable import BasilClient

final class APIErrorServerFailureTests: XCTestCase {
    private func body(_ json: String) -> Data {
        Data(json.utf8)
    }

    func testAPlainTextDetailBecomesTheMessageThePersonSees() {
        let detail = "Not enough free disk space to download Qwen3.6-35B-A3B MLX 4-bit. It needs about 42 GB free while it installs, and this Mac has 30 GB free. Free up about 12 GB and try again."

        let error = APIError.serverFailure(statusCode: 507, body: body("{\"detail\": \"\(detail)\"}"))

        guard case .serverMessage(let statusCode, let message) = error else {
            return XCTFail("Expected a serverMessage, got \(error)")
        }
        XCTAssertEqual(statusCode, 507)
        XCTAssertEqual(message, detail)
        XCTAssertEqual(error.localizedDescription, detail)
    }

    func testAResponseWithoutADetailStaysAStatusOnlyError() {
        let error = APIError.serverFailure(statusCode: 500, body: body("{\"status\": \"error\"}"))

        guard case .serverError(let statusCode) = error else {
            return XCTFail("Expected a serverError, got \(error)")
        }
        XCTAssertEqual(statusCode, 500)
        XCTAssertEqual(error.localizedDescription, "The Basil backend returned an error (HTTP 500).")
    }

    func testAValidationFailureWithAListDetailStaysAStatusOnlyError() {
        let error = APIError.serverFailure(
            statusCode: 422,
            body: body("{\"detail\": [{\"loc\": [\"body\"], \"msg\": \"field required\"}]}")
        )

        guard case .serverError(let statusCode) = error else {
            return XCTFail("Expected a serverError, got \(error)")
        }
        XCTAssertEqual(statusCode, 422)
    }

    func testABlankDetailStaysAStatusOnlyError() {
        let error = APIError.serverFailure(statusCode: 409, body: body("{\"detail\": \"   \"}"))

        guard case .serverError = error else {
            return XCTFail("Expected a serverError, got \(error)")
        }
    }

    func testABodyThatIsNotJSONStaysAStatusOnlyError() {
        let error = APIError.serverFailure(statusCode: 502, body: body("<html>Bad gateway</html>"))

        guard case .serverError(let statusCode) = error else {
            return XCTFail("Expected a serverError, got \(error)")
        }
        XCTAssertEqual(statusCode, 502)
    }

    func testAnEmptyBodyStaysAStatusOnlyError() {
        let error = APIError.serverFailure(statusCode: 503, body: Data())

        guard case .serverError(let statusCode) = error else {
            return XCTFail("Expected a serverError, got \(error)")
        }
        XCTAssertEqual(statusCode, 503)
    }
}
