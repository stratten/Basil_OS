import XCTest
@testable import BasilClient

final class PermissionsSettingsPayloadTests: XCTestCase {
    func testCommandSecurityPatchParsesAllSuppliedFields() {
        let payload: [String: Any] = [
            "approvalMode": "always_prompt",
            "safeExecutionMode": true,
            "autoApproveReadOnly": false,
            "blockDangerousPatterns": true,
            "approvalTimeoutSeconds": 90,
            "timeoutBehavior": "deny_on_timeout",
        ]
        let patch = PermissionsCommandSecurityPatch(payload: payload)
        XCTAssertEqual(patch?.approvalMode, "always_prompt")
        XCTAssertEqual(patch?.safeExecutionMode, true)
        XCTAssertEqual(patch?.autoApproveReadOnly, false)
        XCTAssertEqual(patch?.blockDangerousPatterns, true)
        XCTAssertEqual(patch?.approvalTimeoutSeconds, 90)
        XCTAssertEqual(patch?.timeoutBehavior, "deny_on_timeout")
    }

    func testCommandSecurityPatchLeavesUnsuppliedFieldsNil() {
        let patch = PermissionsCommandSecurityPatch(payload: ["safeExecutionMode": true])
        XCTAssertNil(patch?.approvalMode)
        XCTAssertEqual(patch?.safeExecutionMode, true)
        XCTAssertNil(patch?.autoApproveReadOnly)
        XCTAssertNil(patch?.blockDangerousPatterns)
        XCTAssertNil(patch?.approvalTimeoutSeconds)
        XCTAssertNil(patch?.timeoutBehavior)
    }

    func testCommandSecurityPatchReturnsNilForMissingPayload() {
        XCTAssertNil(PermissionsCommandSecurityPatch(payload: nil))
    }

    func testCommandSecurityPatchRejectsFractionalTimeoutSeconds() {
        XCTAssertNil(PermissionsCommandSecurityPatch(payload: ["approvalTimeoutSeconds": 30.5]))
    }

    func testCommandSecurityPatchIdentifiesEmptyUpdates() {
        XCTAssertTrue(PermissionsCommandSecurityPatch(payload: [:])!.isEmpty)
        XCTAssertFalse(PermissionsCommandSecurityPatch(payload: ["safeExecutionMode": false])!.isEmpty)
    }

    func testApprovalModeRawValuesRoundTripThroughThePatch() {
        let modes: [ExecutionApprovalSettings.ApprovalMode] = [.alwaysApprove, .whitelistOnly, .alwaysPrompt]
        for mode in modes {
            let patch = PermissionsCommandSecurityPatch(payload: ["approvalMode": mode.rawValue])
            XCTAssertEqual(patch?.approvalMode, mode.rawValue)
            XCTAssertNotNil(ExecutionApprovalSettings.ApprovalMode(rawValue: patch!.approvalMode!))
        }
    }

    func testTimeoutBehaviorRawValuesRoundTripThroughThePatch() {
        let behaviors: [ExecutionApprovalSettings.TimeoutBehavior] = [.waitForever, .denyOnTimeout, .retryAlternative]
        for behavior in behaviors {
            let patch = PermissionsCommandSecurityPatch(payload: ["timeoutBehavior": behavior.rawValue])
            XCTAssertEqual(patch?.timeoutBehavior, behavior.rawValue)
            XCTAssertNotNil(ExecutionApprovalSettings.TimeoutBehavior(rawValue: patch!.timeoutBehavior!))
        }
    }
}
