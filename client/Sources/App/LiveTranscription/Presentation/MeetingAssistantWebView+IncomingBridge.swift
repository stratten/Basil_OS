import AppKit
import Foundation
@preconcurrency import WebKit

extension MeetingAssistantWebView {
    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            handleMessage(body: message.body)
        }
    }

    func handleMessage(body: Any) {
        guard let dict = body as? [String: Any],
              let typeString = dict["type"] as? String,
              let intent = MeetingBridgeIntent(rawValue: typeString) else {
            #if DEBUG
            DevLogger.shared.info("[MeetingAssistantWebView \(instanceId)] Unknown or malformed message", context: "LiveTranscription")
            #endif
            return
        }

        // `closeWindow`, `minimizeWindow`, `toggleWindowCollapse`, and
        // `chromeHeight` are handled here because they are pure
        // chrome concerns of this host;
        // every other intent is forwarded, still typed, to the coordinator via
        // `onIntent`, which validates domain-specific fields (e.g. resolving a
        // process id against `availableAudioProcesses`) before mutating the
        // shared view model. `reactReady` is both recorded here and forwarded
        // so an analysis window can deliver its pending result after the
        // renderer handshake.
        switch intent {
        case .reactReady:
            guard (dict["protocolVersion"] as? NSNumber)?.intValue == meetingBridgeProtocolVersion else {
                #if DEBUG
                DevLogger.shared.error("[MeetingAssistantWebView \(instanceId)] Rejected unsupported bridge protocol", context: "LiveTranscription")
                #endif
                return
            }
            hasReceivedReady = true
            onIntent?(intent, dict)
        case .closeWindow:
            onClose?()
        case .minimizeWindow:
            onMinimize?()
        case .toggleWindowCollapse:
            guard let collapsed = dict["collapsed"] as? Bool else { return }
            onToggleCollapse?(collapsed)
        case .chromeHeight:
            guard let height = (dict["height"] as? NSNumber)?.doubleValue,
                  height.isFinite,
                  height > 0 else {
                return
            }
            updateDragAreaHeight(CGFloat(height))
        default:
            onIntent?(intent, dict)
        }
    }
}
