import Foundation

@MainActor
protocol ReactWritingExamplesSettingsBridgeOutput: AnyObject {
    func sendInit(activeFilter: ReactWritingExamplesFilter, samples: [WritingSample], styleProfile: CommunicationStyleProfile?, isLoadingSamples: Bool)
    func sendSnapshot(activeFilter: ReactWritingExamplesFilter, samples: [WritingSample], styleProfile: CommunicationStyleProfile?, isLoadingSamples: Bool)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactWritingExamplesSettingsWebView: ReactWritingExamplesSettingsBridgeOutput {
    func sendInit(activeFilter: ReactWritingExamplesFilter, samples: [WritingSample], styleProfile: CommunicationStyleProfile?, isLoadingSamples: Bool) {
        var event = stateEvent(type: "init", activeFilter: activeFilter, samples: samples, styleProfile: styleProfile, isLoadingSamples: isLoadingSamples)
        event["protocolVersion"] = 1
        callJS("window.basilWritingExamplesSettings && window.basilWritingExamplesSettings.onEvent", args: event)
    }

    func sendSnapshot(activeFilter: ReactWritingExamplesFilter, samples: [WritingSample], styleProfile: CommunicationStyleProfile?, isLoadingSamples: Bool) {
        let event = stateEvent(type: "snapshot", activeFilter: activeFilter, samples: samples, styleProfile: styleProfile, isLoadingSamples: isLoadingSamples)
        callJS("window.basilWritingExamplesSettings && window.basilWritingExamplesSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = [
            "type": "intentResult",
            "requestId": requestId,
            "status": status,
        ]
        if let message {
            event["message"] = message
        }
        callJS("window.basilWritingExamplesSettings && window.basilWritingExamplesSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = [
            "type": "loadError",
            "message": message,
        ]
        callJS("window.basilWritingExamplesSettings && window.basilWritingExamplesSettings.onEvent", args: event)
    }

    private func stateEvent(
        type: String,
        activeFilter: ReactWritingExamplesFilter,
        samples: [WritingSample],
        styleProfile: CommunicationStyleProfile?,
        isLoadingSamples: Bool
    ) -> [String: Any] {
        let isoFormatter = ISO8601DateFormatter()
        return [
            "type": type,
            "activeFilter": activeFilter.rawValue,
            "isLoadingSamples": isLoadingSamples,
            "samples": samples.map { sample in
                [
                    "id": sample.id,
                    "contextType": sample.context_type,
                    "content": sample.content,
                    "recipient": sample.recipient ?? NSNull(),
                    "createdAt": isoFormatter.string(from: sample.created_at),
                ] as [String: Any]
            },
            "styleProfile": styleProfile.map { profile in
                [
                    "contextType": profile.context_type,
                    "confidence": profile.confidence,
                    "sampleCount": profile.sample_count,
                    "styleAttributes": [
                        "formalityLevel": profile.style_attributes.formality_level,
                        "avgSentenceLength": profile.style_attributes.avg_sentence_length,
                        "greetingPatterns": profile.style_attributes.greeting_patterns,
                        "closingPatterns": profile.style_attributes.closing_patterns,
                        "toneMarkers": profile.style_attributes.tone_markers,
                        "paragraphStructure": profile.style_attributes.paragraph_structure,
                        "styleSummary": profile.style_attributes.style_summary ?? NSNull(),
                    ] as [String: Any],
                ] as [String: Any]
            } ?? NSNull(),
        ]
    }
}
