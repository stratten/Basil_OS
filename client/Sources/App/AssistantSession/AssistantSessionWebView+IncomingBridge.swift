import WebKit

extension AssistantSessionWebView {
    func handleScriptMessage(_ message: WKScriptMessage) {
        if message.name == "jsLog" {
            #if DEBUG
            if let body = message.body as? [String: Any] {
                let kind = (body["kind"] as? String) ?? (body["level"] as? String) ?? "log"
                let text = (body["message"] as? String) ?? ""
                DevLogger.shared.info("[ASSISTANT_SESSION_WEB:\(kind)] \(text)", context: "AssistantSessionWebView")
            }
            #endif
            return
        }

        guard message.name == "assistantSessionBridge",
              let body = message.body as? [String: Any],
              let type = body["type"] as? String else {
            return
        }

        switch type {
        case "reactReady":
            guard (body["protocolVersion"] as? NSNumber)?.intValue == 1 else {
                #if DEBUG
                DevLogger.shared.error("[ASSISTANT_SESSION_WEB] React reported an unsupported protocol version", context: "AssistantSessionWebView")
                #endif
                return
            }
            markReadyFromReact()
        case "requestResize":
            guard let width = body["width"] as? Double, let height = body["height"] as? Double else { return }
            onResize?(CGFloat(width), CGFloat(height))
        case "showNativeModelPicker":
            guard let rawModels = body["models"] as? [[String: Any]],
                  let rawAnchorRect = body["anchorRect"] as? [String: Any],
                  let x = rawAnchorRect["x"] as? Double,
                  let y = rawAnchorRect["y"] as? Double,
                  let width = rawAnchorRect["width"] as? Double,
                  let height = rawAnchorRect["height"] as? Double else {
                return
            }
            let models = rawModels.compactMap { rawModel -> AssistantSessionModelPickerOption? in
                guard let id = rawModel["id"] as? String,
                      let displayName = rawModel["displayName"] as? String,
                      let isApiModel = rawModel["isApiModel"] as? Bool else {
                    return nil
                }
                return AssistantSessionModelPickerOption(
                    id: id,
                    displayName: displayName,
                    category: isApiModel ? "api" : "local"
                )
            }
            let anchorRect = NativeModelPickerPopoverSupport.anchorRect(
                webX: CGFloat(x),
                webY: CGFloat(y),
                width: CGFloat(width),
                height: CGFloat(height),
                hostBounds: webView.bounds,
                hostIsFlipped: webView.isFlipped
            )
            showNativeModelPicker(
                models: models,
                selectedModelId: body["selectedModelId"] as? String,
                anchorRect: anchorRect
            )
        default:
            onIntent?(body)
        }
    }
}
