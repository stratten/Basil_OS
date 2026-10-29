import AppKit

extension AgentTaskResultWidgetController {
    func dispatchOrQueueWebCommand(_ command: PendingWebCommand) {
        guard isWebViewReady, let webView else {
            pendingWebCommands.append(command)
            #if DEBUG
            DevLogger.shared.info(
                "[AgentTaskResult] Queued web command while result widget initializes; queued=\(pendingWebCommands.count)",
                context: "AgentTaskResult"
            )
            #endif
            webView?.forceInitRetry()
            return
        }

        sendWebCommand(command, to: webView)
    }

    func handleWebViewReady() {
        guard let webView else { return }
        isWebViewReady = true
        let commands = pendingWebCommands
        pendingWebCommands.removeAll()

        #if DEBUG
        DevLogger.shared.info(
            "[AgentTaskResult] Result webview ready; flushing queued commands=\(commands.count)",
            context: "AgentTaskResult"
        )
        #endif

        for command in commands {
            sendWebCommand(command, to: webView)
        }
        sendWebCommand(
            .detachedRoots(
                rootTaskIds: DetachedAgentTaskWindowManager.shared.detachedRootTaskIds
            ),
            to: webView
        )
    }

    func sendWebCommand(_ command: PendingWebCommand, to webView: AgentTaskResultWebView) {
        switch command {
        case .register(let agentTaskId, let referencePaths):
            #if DEBUG
            DevLogger.shared.info(
                "[AgentTaskResult] Sending register command to webview \(webView.instanceId): \(agentTaskId)",
                context: "AgentTaskResult"
            )
            #endif
            webView.sendRegisterAndSelectAgent(agentTaskId: agentTaskId, referencePaths: referencePaths)
        case .showExisting(let agentTaskId):
            #if DEBUG
            DevLogger.shared.info(
                "[AgentTaskResult] Sending show-existing command to webview \(webView.instanceId): \(agentTaskId)",
                context: "AgentTaskResult"
            )
            #endif
            webView.sendShowExistingAgentTask(agentTaskId: agentTaskId)
        case .showScheduled(let scheduledAgentTaskId):
            webView.sendShowScheduledAgentTask(scheduledAgentTaskId: scheduledAgentTaskId)
        case .restoreValidationManagedHistory(let requestId):
            webView.sendRestoreValidationManagedHistory(requestId: requestId)
        case .detachedRoots(let rootTaskIds):
            webView.sendDetachedRootsChanged(rootTaskIds: rootTaskIds)
        }
    }
}
