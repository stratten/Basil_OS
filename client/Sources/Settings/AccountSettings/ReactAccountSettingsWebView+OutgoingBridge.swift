import Foundation

@MainActor
protocol ReactAccountSettingsBridgeOutput: AnyObject {
    func sendInit(viewModel: AccountSettingsViewModel)
    func sendSnapshot(viewModel: AccountSettingsViewModel)
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactAccountSettingsWebView: ReactAccountSettingsBridgeOutput {
    func sendInit(viewModel: AccountSettingsViewModel) {
        var event = stateEvent(type: "init", viewModel: viewModel)
        event["protocolVersion"] = 1
        callJS("window.basilAccountSettings && window.basilAccountSettings.onEvent", args: event)
    }

    func sendSnapshot(viewModel: AccountSettingsViewModel) {
        let event = stateEvent(type: "snapshot", viewModel: viewModel)
        callJS("window.basilAccountSettings && window.basilAccountSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilAccountSettings && window.basilAccountSettings.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilAccountSettings && window.basilAccountSettings.onEvent", args: event)
    }

    private func stateEvent(type: String, viewModel vm: AccountSettingsViewModel) -> [String: Any] {
        [
            "type": type,
            "isAuthenticated": vm.isAuthenticated,
            "userEmail": vm.userEmail,
            "subscriptionStatus": vm.subscriptionStatus,
            "hasPaymentMethod": vm.hasPaymentMethod,
            "cardBrand": vm.hasPaymentMethod ? vm.cardBrandFormatted : "",
            "cardLast4": vm.cardLast4,
            "cardExpiration": vm.hasPaymentMethod ? vm.cardExpirationFormatted : "",
            "apiKeyPreference": vm.apiKeyPreference.rawValue,
            "basilCloudSelected": vm.basilCloudSelected,
            "basilCloudBadge": vm.basilCloudBadge,
            "basilCloudDescription": vm.basilCloudDescription,
            "isLoadingUsage": vm.isLoadingUsage,
            "currentPeriodFormatted": vm.currentPeriodFormatted,
            "totalCostFormatted": vm.totalCostFormatted,
            "totalTokensFormatted": vm.totalTokensFormatted,
            "usageByModel": vm.usageByModel.keys.sorted().map { model -> [String: Any] in
                ["model": model, "costUsd": vm.usageByModel[model]?.costUsd ?? 0]
            },
        ]
    }
}
