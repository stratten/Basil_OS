import Foundation

@MainActor
protocol HotkeySettingsBridgeOutput: AnyObject {
    func sendInit(rows: [HotkeyRowDefinition], bindings: [String: HotkeyBinding], enableMonitoringAtStartup: Bool)
    func sendSnapshot(rows: [HotkeyRowDefinition], bindings: [String: HotkeyBinding], enableMonitoringAtStartup: Bool)
    func sendLoadError(message: String)
    func sendCaptured(id: String, binding: HotkeyBinding)
    func sendCaptureCanceled(id: String)
    func sendIntentResult(requestId: String, status: String, message: String?)
}

extension HotkeySettingsWebView: HotkeySettingsBridgeOutput {
    func sendInit(rows: [HotkeyRowDefinition], bindings: [String: HotkeyBinding], enableMonitoringAtStartup: Bool) {
        var event = rowsPayload(rows: rows, bindings: bindings, enableMonitoringAtStartup: enableMonitoringAtStartup)
        event["type"] = "init"
        event["protocolVersion"] = 1
        callJS("window.basilHotkeySettings && window.basilHotkeySettings.onEvent", args: event)
    }

    func sendSnapshot(rows: [HotkeyRowDefinition], bindings: [String: HotkeyBinding], enableMonitoringAtStartup: Bool) {
        var event = rowsPayload(rows: rows, bindings: bindings, enableMonitoringAtStartup: enableMonitoringAtStartup)
        event["type"] = "snapshot"
        callJS("window.basilHotkeySettings && window.basilHotkeySettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilHotkeySettings && window.basilHotkeySettings.onEvent", args: event)
    }

    func sendCaptured(id: String, binding: HotkeyBinding) {
        let event: [String: Any] = [
            "type": "captured",
            "id": id,
            "binding": bindingPayload(binding),
        ]
        callJS("window.basilHotkeySettings && window.basilHotkeySettings.onEvent", args: event)
    }

    func sendCaptureCanceled(id: String) {
        let event: [String: Any] = ["type": "captureCanceled", "id": id]
        callJS("window.basilHotkeySettings && window.basilHotkeySettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilHotkeySettings && window.basilHotkeySettings.onEvent", args: event)
    }

    private func bindingPayload(_ binding: HotkeyBinding) -> [String: Any] {
        [
            "key": binding.key,
            "enabled": binding.enabled,
            "modifiers": binding.modifiers,
            "isDoublePress": binding.isDoublePress,
            "doublePressKey": binding.doublePressKey as Any,
        ]
    }

    private func rowsPayload(rows: [HotkeyRowDefinition], bindings: [String: HotkeyBinding], enableMonitoringAtStartup: Bool) -> [String: Any] {
        let rowPayloads: [[String: Any]] = rows.map { row in
            let binding = bindings[row.id] ?? HotkeyRowCatalog.defaultBinding(for: row.id)
            return [
                "id": row.id,
                "title": row.title,
                "subtitle": row.subtitle as Any,
                "binding": bindingPayload(binding),
            ]
        }
        return [
            "rows": rowPayloads,
            "enableMonitoringAtStartup": enableMonitoringAtStartup,
        ]
    }
}
