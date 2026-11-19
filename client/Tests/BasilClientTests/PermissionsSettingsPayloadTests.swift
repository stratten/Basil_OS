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

    func testModelJudgeSettingTravelsThroughThePatchAndTheUpdateRequest() throws {
        let patch = PermissionsCommandSecurityPatch(payload: ["modelJudgesCommandSafety": true])
        XCTAssertEqual(patch?.modelJudgesCommandSafety, true)
        XCTAssertFalse(patch!.isEmpty)

        let request = patch!.updateRequest()
        XCTAssertEqual(request.modelJudgesCommandSafety, true)
        let encoded = try JSONEncoder().encode(request)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        XCTAssertEqual(json["model_judges_command_safety"] as? Bool, true)
    }

    func testModelJudgeSettingIsOffWhenAnOlderBackendDoesNotSendIt() throws {
        let body = """
        {"approval_mode": "whitelist_only", "show_full_command_in_prompt": true, "remember_choice_option": true, "auto_approve_read_only": true, "block_dangerous_patterns": true, "whitelisted_count": 0}
        """
        let settings = try JSONDecoder().decode(ExecutionApprovalSettings.self, from: Data(body.utf8))
        XCTAssertFalse(settings.modelJudgesCommandSafety)

        let withIt = body.replacingOccurrences(of: "\"whitelisted_count\": 0", with: "\"whitelisted_count\": 0, \"model_judges_command_safety\": true")
        XCTAssertTrue(try JSONDecoder().decode(ExecutionApprovalSettings.self, from: Data(withIt.utf8)).modelJudgesCommandSafety)
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
