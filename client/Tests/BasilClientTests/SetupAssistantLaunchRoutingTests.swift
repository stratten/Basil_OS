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

final class SetupAssistantFirstRunGateTests: XCTestCase {
    func testMissingPermissionsShowThePermissionsWindowFirst() {
        XCTAssertEqual(
            SetupAssistantFirstRunGate.nextStep(allRequiredPermissionsGranted: false, isValidationProfile: false),
            .showPermissions
        )
    }

    func testGrantedPermissionsOpenTheAssistantDirectly() {
        XCTAssertEqual(
            SetupAssistantFirstRunGate.nextStep(allRequiredPermissionsGranted: true, isValidationProfile: false),
            .showAssistant
        )
    }

    func testValidationProfileAlwaysOpensTheAssistantDirectly() {
        XCTAssertEqual(
            SetupAssistantFirstRunGate.nextStep(allRequiredPermissionsGranted: false, isValidationProfile: true),
            .showAssistant
        )
        XCTAssertEqual(
            SetupAssistantFirstRunGate.nextStep(allRequiredPermissionsGranted: true, isValidationProfile: true),
            .showAssistant
        )
    }
}
