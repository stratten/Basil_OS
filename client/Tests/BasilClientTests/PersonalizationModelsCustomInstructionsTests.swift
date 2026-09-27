import XCTest
@testable import BasilClient

final class PersonalizationModelsCustomInstructionsTests: XCTestCase {
    func testUserProfileDecodesCustomInstructions() throws {
        let json = """
        {"id":"default","custom_instructions":"No em dashes.","created_at":null,"updated_at":null,"profile_version":1}
        """.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .customISO8601
        let profile = try decoder.decode(UserProfile.self, from: json)
        XCTAssertEqual(profile.custom_instructions, "No em dashes.")
    }

    func testUserProfileCreateEncodesCustomInstructions() throws {
        let payload = UserProfileCreate(custom_instructions: "Minimize exclamation points.")
        let encoder = JSONEncoder()
        let data = try encoder.encode(payload)
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(obj?["custom_instructions"] as? String, "Minimize exclamation points.")
    }

    func testUserProfileIsEmptyAccountsForCustomInstructions() {
        let profile = UserProfile(
            id: "default", full_name: nil, preferred_name: nil, email: nil,
            job_title: nil, company_name: nil, industry: nil,
            default_formality: nil, default_tone: nil, custom_instructions: "Be terse.",
            created_at: nil, updated_at: nil, profile_version: nil
        )
        XCTAssertFalse(profile.isEmpty, "A profile with only custom_instructions set must not report isEmpty")
    }
}
