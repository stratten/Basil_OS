import Foundation
@preconcurrency import WebKit

extension MeetingAssistantWebView {
    func send(_ event: MeetingBridgeEvent) {
        callJS("window.basilMeetingAssistant?.onEvent", args: encodeToJSONObject(event) ?? [:])
    }

    func publishMeter(_ payload: MeetingMeterPayload) {
        callJS("window.basilMeetingAssistant?.onMeter", args: encodeToJSONObject(payload) ?? [:])
    }

    private func encodeToJSONObject<T: Encodable>(_ value: T) -> Any? {
        guard let data = try? JSONEncoder().encode(value) else { return nil }
        return try? JSONSerialization.jsonObject(with: data)
    }

    func callJS(_ function: String, args: Any...) {
        guard args.count == 1 else { return }
        webView.callAsyncJavaScript(
            "\(function)(event)",
            arguments: ["event": args[0]],
            in: nil,
            in: .page
        ) { result in
            if case .failure(let error) = result {
                #if DEBUG
                DevLogger.shared.error("[MeetingAssistantWebView \(self.instanceId)] JS eval error: \(error)", context: "LiveTranscription")
                #endif
            }
        }
    }
}
