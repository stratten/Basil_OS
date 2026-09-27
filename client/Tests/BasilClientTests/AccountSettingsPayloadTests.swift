import XCTest
@testable import BasilClient

final class AccountSettingsPayloadTests: XCTestCase {
    func testDeleteAccountResponseDecodesFinalInvoice() throws {
        let json = """
        {"success": true, "message": "Account deleted successfully", "final_invoice": {"invoice_id": "in_123", "amount_charged": 4.5}}
        """.data(using: .utf8)!
        let response = try JSONDecoder().decode(DeleteAccountResponse.self, from: json)
        XCTAssertTrue(response.success)
        XCTAssertEqual(response.message, "Account deleted successfully")
        XCTAssertEqual(response.finalInvoice?.invoiceId, "in_123")
        XCTAssertEqual(response.finalInvoice?.amountCharged, 4.5)
    }

    func testDeleteAccountResponseWithoutFinalInvoiceDecodesNil() throws {
        let json = """
        {"success": true, "message": "Account deleted successfully"}
        """.data(using: .utf8)!
        let response = try JSONDecoder().decode(DeleteAccountResponse.self, from: json)
        XCTAssertTrue(response.success)
        XCTAssertNil(response.finalInvoice)
    }

    func testAccountDeletionBlockedSurfacesServerMessageVerbatim() {
        let error = AuthError.accountDeletionBlocked("You have an outstanding balance of $12.34.")
        XCTAssertEqual(error.errorDescription, "You have an outstanding balance of $12.34.")
    }

    func testOtherAuthErrorsRetainTheirExistingDescriptions() {
        // Regression guard: adding the new case must not change any
        // existing case's message.
        XCTAssertEqual(AuthError.invalidCredentials.errorDescription, "Invalid email or password")
        XCTAssertEqual(AuthError.notAuthenticated.errorDescription, "Not authenticated")
    }
}
