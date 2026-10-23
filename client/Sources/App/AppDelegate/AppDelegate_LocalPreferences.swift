import Foundation

// MARK: - Local Backend Preferences

struct LocalPreferences: Decodable {
    struct General: Decodable {
        let has_completed_onboarding: Bool?
    }

    struct Behavior: Decodable {
        let enable_voice_listener_at_startup: Bool?
        let enable_monitoring_at_startup: Bool?
    }

    let general: General?
    let behavior: Behavior?
}

func readLocalPreferences() -> LocalPreferences? {
    let prefsPath = (BasilRuntimeProfile.localHomeURL as NSURL)
        .appendingPathComponent(".config/basil/preferences.json")?.path
    guard let path = prefsPath, FileManager.default.fileExists(atPath: path) else { return nil }
    do {
        let data = try Data(contentsOf: URL(fileURLWithPath: path))
        return try JSONDecoder().decode(LocalPreferences.self, from: data)
    } catch { return nil }
}
