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
        webView.callBasilEventHandler(
            function,
            event: args[0],
            logTag: "MeetingAssistantWebView \(instanceId)",
            logContext: "LiveTranscription"
        )
    }
}
