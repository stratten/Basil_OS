import XCTest
@testable import BasilClient

final class SetupAccountCredentialValidationTests: XCTestCase {
    func testLoginRequiresAnEmailAddressAndAPassword() {
        XCTAssertNotNil(SetupAccountCredentialValidation.loginError(email: "", password: "secret"))
        XCTAssertNotNil(SetupAccountCredentialValidation.loginError(email: "   ", password: "secret"))
        XCTAssertNotNil(SetupAccountCredentialValidation.loginError(email: "not-an-email", password: "secret"))
        XCTAssertNotNil(SetupAccountCredentialValidation.loginError(email: "me@example.com", password: ""))
        XCTAssertNil(SetupAccountCredentialValidation.loginError(email: " me@example.com ", password: "secret"))
    }

    func testLoginDoesNotApplyTheSignupLengthRuleToExistingAccounts() {
        XCTAssertNil(SetupAccountCredentialValidation.loginError(email: "me@example.com", password: "short"))
    }

    func testSignupRequiresAtLeastEightCharacters() {
        XCTAssertEqual(
            SetupAccountCredentialValidation.signupError(email: "me@example.com", password: "1234567", confirmPassword: "1234567"),
            "Password must be at least 8 characters."
        )
        XCTAssertNil(
            SetupAccountCredentialValidation.signupError(email: "me@example.com", password: "12345678", confirmPassword: "12345678")
        )
    }

    func testSignupRequiresTheConfirmationToMatch() {
        XCTAssertEqual(
            SetupAccountCredentialValidation.signupError(email: "me@example.com", password: "12345678", confirmPassword: "12345679"),
            "Passwords don’t match."
        )
    }

    func testSignupReportsAMissingEmailBeforePasswordProblems() {
        XCTAssertEqual(
            SetupAccountCredentialValidation.signupError(email: "", password: "x", confirmPassword: "y"),
            "Enter the email address for your Basil account."
        )
    }

    func testThePaymentPageIsAnHTTPSAddressThatParses() throws {
        let url = try XCTUnwrap(URL(string: SetupAccountLinks.paymentSetupURLString))
        XCTAssertEqual(url.scheme, "https")
        XCTAssertEqual(url.path, "/web/payment")
    }
}
