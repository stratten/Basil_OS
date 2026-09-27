import AppKit
import Combine

extension AgentTaskResultEmbeddedHost {
    func handleFollowUpCaptureStart(rootTaskId: String, previousTaskId: String? = nil) {
        guard followUpCaptureVM == nil else { return }
        let followUpId = UUID().uuidString
        let resolvedPreviousTaskId = previousTaskId ?? rootTaskId
        let captureVM = AgentTaskCaptureViewModel(
            rootTaskId: rootTaskId,
            previousTaskId: resolvedPreviousTaskId
        )
        guard AgentTaskFollowUpCaptureLease.shared.acquire(
            ownerID: followUpCaptureOwnerID,
            onComplete: { [weak captureVM] in captureVM?.completeCapture() },
            onCancel: { [weak captureVM] in captureVM?.cancelCapture() }
        ) else {
            webView.sendCaptureStateChanged(
                type: "followUp",
                isCapturing: false,
                wordsDetected: "Another AgentTask window is recording.",
                audioLevel: 0,
                silenceProgress: 0
            )
            return
        }
        captureVM.preGeneratedAgentTaskId = followUpId
        self.followUpCaptureVM = captureVM
        self.followUpCancellables.removeAll()

        captureVM.onCaptureComplete = { [weak self] in
            guard let self = self else { return }
            self.webView.sendCaptureStateChanged(
                type: "followUp", isCapturing: false,
                wordsDetected: "", audioLevel: 0, silenceProgress: 0
            )
            self.followUpCaptureVM = nil
            self.followUpCancellables.removeAll()
            AgentTaskFollowUpCaptureLease.shared.release(ownerID: self.followUpCaptureOwnerID)

            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
                self?.webView.sendRegisterAndSelectAgent(
                    agentTaskId: followUpId,
                    rootTaskId: rootTaskId,
                    previousTaskId: resolvedPreviousTaskId
                )
            }
        }
        captureVM.onCaptureCanceled = { [weak self] in
            guard let self else { return }
            self.followUpCaptureVM = nil
            self.followUpCancellables.removeAll()
            AgentTaskFollowUpCaptureLease.shared.release(ownerID: self.followUpCaptureOwnerID)
            self.webView.sendCaptureStateChanged(
                type: "followUp",
                isCapturing: false,
                wordsDetected: "",
                audioLevel: 0,
                silenceProgress: 0
            )
        }

        Publishers.CombineLatest(captureVM.$wordsDetected, captureVM.$audioLevel)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] words, level in
                self?.webView.sendCaptureStateChanged(
                    type: "followUp", isCapturing: true,
                    wordsDetected: words.joined(separator: " "),
                    audioLevel: level, silenceProgress: 0
                )
            }
            .store(in: &followUpCancellables)

        webView.sendCaptureStateChanged(
            type: "followUp", isCapturing: true,
            wordsDetected: "", audioLevel: 0, silenceProgress: 0
        )

        captureVM.startCapture()
    }

    func handleFollowUpCaptureStop() {
        followUpCaptureVM?.completeCapture()
    }

    func handleFollowUpCaptureCancel() {
        followUpCaptureVM?.cancelCapture()
        followUpCaptureVM = nil
        followUpCancellables.removeAll()
        AgentTaskFollowUpCaptureLease.shared.release(ownerID: followUpCaptureOwnerID)
        webView.sendCaptureStateChanged(
            type: "followUp", isCapturing: false,
            wordsDetected: "", audioLevel: 0, silenceProgress: 0
        )
    }

    func handleRefinementStart() {
        webView.sendCaptureStateChanged(
            type: "refinement", isCapturing: true,
            wordsDetected: "", audioLevel: 0, silenceProgress: 0
        )
    }

    func handleRefinementStop() {
        webView.sendCaptureStateChanged(
            type: "refinement", isCapturing: false,
            wordsDetected: "", audioLevel: 0, silenceProgress: 0
        )
    }

    @discardableResult
    func cancelActiveFollowUpCapture() -> Bool {
        guard followUpCaptureVM != nil else { return false }
        handleFollowUpCaptureCancel()
        return true
    }

    var isFollowUpCapturing: Bool {
        followUpCaptureVM?.isCapturing == true
    }

    @discardableResult
    func completeActiveFollowUpCapture() -> Bool {
        guard let vm = followUpCaptureVM, vm.isCapturing else { return false }
        vm.completeCapture()
        return true
    }
}
