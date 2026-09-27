import Foundation

extension WebSocketService {
    @MainActor
    func handleAppearanceUpdated(_ json: [String: Any]) {
        guard let appearanceSettings = json["appearance_settings"] as? [String: Any],
              let data = try? JSONSerialization.data(withJSONObject: appearanceSettings),
              let settings = try? JSONDecoder().decode(AppearanceSettings.self, from: data) else {
            #if DEBUG
            DevLogger.shared.error("Invalid appearance_updated event", context: "websocket")
            #endif
            return
        }

        if let revision = json["revision"] as? Int {
            AestheticSystem.recordRemoteAppearanceRevision(revision)
        }
        APIClient.shared.cacheAppearanceSettings(settings)
    }
}
