import XCTest
@testable import BasilClient

final class SetupAssistantLaunchRoutingTests: XCTestCase {
    func testCompletedOnboardingPresentsNothingEvenWithAStalePendingFlag() {
        XCTAssertEqual(
            SetupAssistantLaunchRouting.route(backendHasCompletedOnboarding: true, pendingSetupAssistant: true),
            .nothing
        )
        XCTAssertEqual(
            SetupAssistantLaunchRouting.route(backendHasCompletedOnboarding: true, pendingSetupAssistant: false),
            .nothing
        )
    }

    func testSkippedSetupOnlyChecksPermissions() {
        XCTAssertEqual(
            SetupAssistantLaunchRouting.route(backendHasCompletedOnboarding: false, pendingSetupAssistant: true),
            .permissionsCheckOnly
        )
        XCTAssertEqual(
            SetupAssistantLaunchRouting.route(backendHasCompletedOnboarding: nil, pendingSetupAssistant: true),
            .permissionsCheckOnly
        )
    }

    func testFirstRunOpensTheFullSetupAssistant() {
        XCTAssertEqual(
            SetupAssistantLaunchRouting.route(backendHasCompletedOnboarding: false, pendingSetupAssistant: false),
            .primarySetupFlow
        )
        XCTAssertEqual(
            SetupAssistantLaunchRouting.route(backendHasCompletedOnboarding: nil, pendingSetupAssistant: false),
            .primarySetupFlow
        )
    }
}
