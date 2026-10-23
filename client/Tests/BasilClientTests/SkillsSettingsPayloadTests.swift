import XCTest
@testable import BasilClient

final class SkillsSettingsPayloadTests: XCTestCase {
    func testMakesSnapshotPayloadFromExplicitFields() throws {
        let candidate = SkillCandidateDTO(
            id: "c1", title: "Draft weekly report", whenToUse: "When asked to summarize the week",
            triggers: [], procedureMarkdown: "", expectedResult: "", sourceTaskIds: [],
            source: "auto", createdAt: "2026-08-01T00:00:00Z", status: "pending", observationCount: 3
        )
        let skill = SkillDTO(
            slug: "weekly-report", title: "Weekly report", whenToUse: "Weekly summaries",
            triggers: [], sizeBytes: 512, capBytes: 2048, lastUsed: "2026-08-20T00:00:00Z",
            observationCount: 5, version: 2
        )
        let model = ReasoningModelInfo(id: "m1", name: "local-1", displayName: "Local Model", provider: "local", isApiModel: false)

        let payload = SkillsSettingsPayloadBuilder.makeSnapshotPayload(
            skillCandidates: [candidate],
            savedSkills: [skill],
            reconciliationActive: true,
            skillAfterTaskEnabled: true,
            skillDailyEnabled: false,
            skillDailyTimeLocal: "03:00",
            skillProcessingModel: nil,
            skillReconciliationMinInstances: 2,
            availableSkillProcessingModels: [model],
            pendingCandidateActionIDs: ["c1"],
            pendingSkillDeletionSlugs: [],
            isLoadingSkillsState: false,
            isRunningSkillsIntelligence: false,
            skillsStatusMessage: nil
        )

        XCTAssertEqual(payload["reconciliationActive"] as? Bool, true)
        XCTAssertEqual(payload["skillAfterTaskEnabled"] as? Bool, true)
        XCTAssertEqual(payload["skillReconciliationMinInstances"] as? Int, 2)
        XCTAssertTrue(payload["skillProcessingModel"] is NSNull)
        XCTAssertTrue(payload["statusMessage"] is NSNull)

        let candidates = try XCTUnwrap(payload["skillCandidates"] as? [[String: Any]])
        XCTAssertEqual(candidates.count, 1)
        XCTAssertEqual(candidates[0]["id"] as? String, "c1")
        XCTAssertEqual(candidates[0]["observationCount"] as? Int, 3)

        let skills = try XCTUnwrap(payload["savedSkills"] as? [[String: Any]])
        XCTAssertEqual(skills.count, 1)
        XCTAssertEqual(skills[0]["slug"] as? String, "weekly-report")
        XCTAssertEqual(skills[0]["lastUsed"] as? String, "2026-08-20T00:00:00Z")

        let pending = try XCTUnwrap(payload["pendingCandidateActionIDs"] as? [String])
        XCTAssertEqual(pending, ["c1"])
    }

    func testEncodesNilLastUsedAsNSNull() throws {
        let skill = SkillDTO(
            slug: "no-last-used", title: "Never used", whenToUse: "n/a",
            triggers: [], sizeBytes: 0, capBytes: 1024, lastUsed: nil,
            observationCount: 0, version: 1
        )
        let payload = SkillsSettingsPayloadBuilder.makeSkillPayload(skill)
        XCTAssertTrue(payload["lastUsed"] is NSNull)
    }

    func testStatusMessageErrorHeuristicRoundTrips() throws {
        let payload = SkillsSettingsPayloadBuilder.makeSnapshotPayload(
            skillCandidates: [], savedSkills: [], reconciliationActive: false,
            skillAfterTaskEnabled: false, skillDailyEnabled: false, skillDailyTimeLocal: "03:00",
            skillProcessingModel: nil, skillReconciliationMinInstances: 2,
            availableSkillProcessingModels: [], pendingCandidateActionIDs: [], pendingSkillDeletionSlugs: [],
            isLoadingSkillsState: false, isRunningSkillsIntelligence: false,
            skillsStatusMessage: "Error deleting skill: network unavailable"
        )
        XCTAssertEqual(payload["statusMessage"] as? String, "Error deleting skill: network unavailable")
    }
}
