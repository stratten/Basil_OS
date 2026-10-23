import Foundation
@preconcurrency import WebKit

extension AgentTaskResultWebView {
    // MARK: - Swift → JS Messages
    
    func sendInit(port: Int) {
        let wsUrl = "ws://localhost:\(port)/ws"
        
        // Include the centralized state colors (recording + processing) so the
        // React widget renders the same indigo "thinking" bubble and the same
        // red "capturing" bubble as the native UI, instead of falling back to
        // its bundled CSS defaults.
        let theme = agentTaskThemePayload()
        let fonts = agentTaskFontPayload()
        
        var config: [String: Any] = [
            "wsUrl": wsUrl,
            "port": port,
            "theme": theme,
            "fonts": fonts,
            "initiallyProcessing": initiallyProcessing,
            "initialSidebarExpanded": initialSidebarExpanded,
            "dateDisplayStyle": DateDisplayPreferenceStore.shared.style.rawValue,
            "embedded": isEmbedded,
        ]
        if let agentTaskId = initialAgentTaskId {
            config["initialAgentTaskId"] = agentTaskId
        }
        if let agentTask = initialAgentTask {
            config["initialAgentTask"] = agentTask
        }
        if !initialReferencePaths.isEmpty {
            config["initialReferencePaths"] = initialReferencePaths.map { $0.path }
        }
        if let detachedRootTaskId {
            config["detachedRootTaskId"] = detachedRootTaskId
        }
        
        #if DEBUG
        DevLogger.shared.info("[AgentTaskResultWebView \(instanceId)] Sending init for port \(port)", context: "AgentTaskCapture")
        #endif
        callJS("window.basilAgentTask?.onInit", args: config)
    }
    
    func sendCaptureStateChanged(type: String, isCapturing: Bool, wordsDetected: String, audioLevel: Float, silenceProgress: Float) {
        let state: [String: Any] = [
            "type": type,
            "isCapturing": isCapturing,
            "wordsDetected": wordsDetected,
            "audioLevel": audioLevel,
            "silenceProgress": silenceProgress,
        ]
        callJS("window.basilAgentTask.onCaptureStateChanged", args: state)
    }
    
    /// Tell the React result widget that a new agent has just been
    /// kicked off and should be focused.
    ///
    /// `rootTaskId` is the linkage that turns a regular new-agent
    /// registration into a follow-up registration. When it is non-nil,
    /// the React handler folds the new run into the parent's
    /// ``agentTaskHistory`` and keeps the parent card selected, instead
    /// of spawning a brand-new sidebar row and switching focus to it
    /// (which would visually "hide" the parent until the widget was
    /// reopened — see ``AgentTaskResultWidgetController``'s
    /// `handleFollowUpCaptureStart` for the call site that exposed the
    /// regression). Existing non-follow-up call sites
    /// (``installNewAgent``, the ``show()`` initial-AgentTask branch)
    /// continue to omit it and behave identically.
    func sendRegisterAndSelectAgent(
        agentTaskId: String,
        rootTaskId: String? = nil,
        previousTaskId: String? = nil,
        referencePaths: [URL] = []
    ) {
        var data: [String: Any] = [
            "agentTaskId": agentTaskId,
        ]
        if let rootTaskId = rootTaskId {
            data["rootTaskId"] = rootTaskId
        }
        if let previousTaskId = previousTaskId {
            data["previousTaskId"] = previousTaskId
        }
        if !referencePaths.isEmpty {
            data["referencePaths"] = referencePaths.map { $0.path }
        }
        callJS("window.basilAgentTask.onRegisterNewAgent", args: data)
    }

    /// Tell the React result widget to switch focus to an already-running or
    /// completed AgentTask. Used by the scheduled-run mini panel's row click
    /// to deep-link into the matching agent. The handler on the JS side
    /// (``window.basilAgentTask.showExistingAgentTask``) is registered by
    /// ``App.tsx`` and queues the call if React hasn't mounted yet, so it's
    /// safe to invoke even immediately after ``loadContent()``.
    func sendShowExistingAgentTask(agentTaskId: String) {
        callJS("window.basilAgentTask.showExistingAgentTask", args: agentTaskId)
    }

    func sendRequestValidationRunState(requestId: String) {
        callValidationJS(
            member: "onRequestValidationRunState",
            argument: requestId
        )
    }

    func sendFocusValidationRun(requestId: String, runId: String) {
        callValidationJS(
            member: "onFocusValidationRun",
            argument: ["requestId": requestId, "runId": runId]
        )
    }

    func sendRestoreValidationManagedHistory(requestId: String) {
        callValidationJS(
            member: "onRestoreValidationManagedHistory",
            argument: requestId
        )
    }

    private func callValidationJS(member: String, argument: Any, attempt: Int = 0) {
        guard let data = try? JSONSerialization.data(
            withJSONObject: argument,
            options: [.fragmentsAllowed]
        ), let argumentJSON = String(data: data, encoding: .utf8) else {
            return
        }
        let script = """
        (() => {
          const bridge = window.basilAgentTask;
          if (!bridge || typeof bridge.\(member) !== 'function') return false;
          bridge.\(member)(\(argumentJSON));
          return true;
        })()
        """
        webView.evaluateJavaScript(script) { [weak self] result, _ in
            guard let self, (result as? Bool) != true, attempt < 100 else {
                return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                self.callValidationJS(member: member, argument: argument, attempt: attempt + 1)
            }
        }
    }

    func sendShowScheduledAgentTask(scheduledAgentTaskId: String) {
        callJS("window.basilAgentTask.showScheduledAgentTask", args: scheduledAgentTaskId)
    }

    func sendDetachedRootsChanged(rootTaskIds: [String]) {
        callJS("window.basilAgentTask.onDetachedRootsChanged", args: rootTaskIds)
    }

    func sendExpandChromeForTaskCompletion() {
        callJS("window.basilAgentTask.onExpandChromeForTaskCompletion")
    }

    /// Tell the React result widget that the provisional agent_task_id we
    /// pre-registered (when capture handed off) will never be persisted by
    /// the backend (no speech detected, transcription failed, etc.). The
    /// React side removes the transient row (if no durable data has
    /// arrived) or marks it failed with the supplied message. This stops
    /// the 404 polling storm that previously occurred when audio_routes
    /// returned ``processed=false`` but the result widget kept trying to
    /// hydrate the never-persisted ID.
    func sendProvisionalFailed(
        agentTaskId: String,
        reason: String,
        message: String,
        rootTaskId: String? = nil,
        previousTaskId: String? = nil
    ) {
        var payload: [String: Any] = [
            "agentTaskId": agentTaskId,
            "reason": reason,
            "message": message,
        ]
        if let rootTaskId = rootTaskId {
            payload["rootTaskId"] = rootTaskId
        }
        if let previousTaskId = previousTaskId {
            payload["previousTaskId"] = previousTaskId
        }
        callJS("window.basilAgentTask.onProvisionalTaskFailed", args: payload)
    }
    
    func sendThemeChanged() {
        // Mirror sendInit's theme payload so live appearance edits propagate
        // the recording/processing state colors as well as the user-
        // configurable primary/secondary/text/background palette.
        let theme = agentTaskThemePayload()
        let fonts = agentTaskFontPayload()
        callJS("window.basilAgentTask.onThemeChanged", args: theme, fonts)
    }

    /// Push the current date display preference to the React widget so its
    /// history timestamps re-render live when the user changes the setting.
    func sendDateStyleChanged() {
        callJS("window.basilAgentTask.onDateStyleChanged", args: DateDisplayPreferenceStore.shared.style.rawValue)
    }

    func callJS(_ function: String, args: Any...) {
        var namedArguments: [String: Any] = [:]
        var parameterNames: [String] = []
        for (index, value) in args.enumerated() {
            let name = "arg\(index)"
            namedArguments[name] = value
            parameterNames.append(name)
        }
        let callExpression = "\(function)(\(parameterNames.joined(separator: ", ")));"

        webView.callAsyncJavaScript(
            callExpression,
            arguments: namedArguments,
            in: nil,
            in: .page
        ) { result in
            if case .failure(let error) = result {
                #if DEBUG
                DevLogger.shared.error("[AgentTaskResultWebView \(self.instanceId)] JS eval error: \(error)", context: "AgentTaskCapture")
                #endif
            }
        }
    }
}

