import AppKit
import Foundation

extension AppDelegate {
    private static let ambientSuggestionsWSEventName = NSNotification.Name("BasilAmbientSuggestionWSEvent")

    @MainActor
    func ensureAmbientSuggestionsPanelController() -> AmbientSuggestionsPanelWindowController {
        if let existing = ambientSuggestionsPanelController {
            return existing
        }
        let controller = AmbientSuggestionsPanelWindowController()
        ambientSuggestionsPanelController = controller
        return controller
    }

    @MainActor
    func showAmbientSuggestionsPanel() {
        ensureAmbientSuggestionsPanelController().orderFrontIfHidden()
    }

    @MainActor
    func registerAmbientSuggestionsObserver() {
        guard ambientSuggestionsObserverToken == nil else { return }
        let token = NotificationCenter.default.addObserver(
            forName: AppDelegate.ambientSuggestionsWSEventName,
            object: nil,
            queue: .main
        ) { note in
            guard let json = note.userInfo as? [String: Any] else { return }
            Task { @MainActor in
                guard let appDelegate = NSApplication.shared.delegate as? AppDelegate else { return }
                appDelegate.handleAmbientSuggestionWSEvent(json)
            }
        }
        ambientSuggestionsObserverToken = token
    }

    @MainActor
    private func handleAmbientSuggestionWSEvent(_ json: [String: Any]) {
        guard let eventType = json["event_type"] as? String else {
            return
        }
        let controller = ensureAmbientSuggestionsPanelController()
        switch eventType {
        case "ambient_suggestion_status_changed":
            guard let status = json["status"] as? [String: Any] else { return }
            controller.updateStatus(status)
        case "ambient_suggestion_created":
            guard let suggestion = decodeAmbientSuggestion(json["suggestion"]) else { return }
            controller.upsertSuggestion(suggestion)
        case "ambient_suggestion_updated":
            guard let suggestion = decodeAmbientSuggestion(json["suggestion"]) else { return }
            if suggestion.outcome == "suggested" {
                controller.upsertSuggestion(suggestion)
            } else {
                controller.removeSuggestion(suggestion.suggestionId)
            }
        default:
            break
        }
    }

    private func decodeAmbientSuggestion(_ payload: Any?) -> AmbientSuggestionRecord? {
        guard let suggestionPayload = payload as? [String: Any],
              let data = try? JSONSerialization.data(withJSONObject: suggestionPayload),
              let suggestion = try? JSONDecoder().decode(AmbientSuggestionRecord.self, from: data) else {
            return nil
        }
        return suggestion
    }
}
