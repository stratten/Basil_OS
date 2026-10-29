import AppKit

extension AgentTaskResultEmbeddedHost {
    func dispatchOrQueueWebCommand(_ command: AgentTaskResultWidgetController.PendingWebCommand) {
        guard isWebViewReady else {
            pendingWebCommands.append(command)
            webView.forceInitRetry()
            return
        }
        sendWebCommand(command)
    }

    func handleWebViewReady() {
        isWebViewReady = true
        let commands = pendingWebCommands
        pendingWebCommands.removeAll()
        for command in commands { sendWebCommand(command) }
        sendWebCommand(.detachedRoots(rootTaskIds: DetachedAgentTaskWindowManager.shared.detachedRootTaskIds))
    }

    private func sendWebCommand(_ command: AgentTaskResultWidgetController.PendingWebCommand) {
        switch command {
        case .register(let agentTaskId, let referencePaths):
            webView.sendRegisterAndSelectAgent(agentTaskId: agentTaskId, referencePaths: referencePaths)
        case .showExisting(let agentTaskId):
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
