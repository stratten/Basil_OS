import AppKit
import Foundation

extension AgentTaskResultWebView {
    func forceInitRetry() {
        hasReceivedReadyAck = false
        initRetryGeneration = UUID()
        sendInitWhenPortReady(portAttempt: 0, ackAttempt: 0, generation: initRetryGeneration)
    }

    func markReadyFromReact() {
        guard !hasReceivedReadyAck else { return }
        hasReceivedReadyAck = true
        #if DEBUG
        DevLogger.shared.info("[AgentTaskResultWebView \(instanceId)] React ready ack received", context: "AgentTaskCapture")
        #endif
        onReady?()
    }

    func sendInitWhenPortReady(portAttempt: Int = 0, ackAttempt: Int = 0, generation: UUID? = nil) {
        let activeGeneration = generation ?? initRetryGeneration
        guard activeGeneration == initRetryGeneration else { return }
        guard !hasReceivedReadyAck else { return }

        let port = APIClient.shared.currentPort
        guard port > 0 else {
            if portAttempt < 30 {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
                    self?.sendInitWhenPortReady(
                        portAttempt: portAttempt + 1,
                        ackAttempt: ackAttempt,
                        generation: activeGeneration
                    )
                }
            } else {
                #if DEBUG
                DevLogger.shared.error("[AgentTaskResultWebView \(instanceId)] API port unavailable after init retry window", context: "AgentTaskCapture")
                #endif
            }
            return
        }

        sendInit(port: port)
        fadeInWebView()

        if ackAttempt < maxInitAckRetries {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
                guard let self else { return }
                guard activeGeneration == self.initRetryGeneration else { return }
                guard !self.hasReceivedReadyAck else { return }
                #if DEBUG
                DevLogger.shared.info("[AgentTaskResultWebView \(self.instanceId)] Retrying init waiting for ready ack (attempt \(ackAttempt + 1))", context: "AgentTaskCapture")
                #endif
                self.sendInitWhenPortReady(
                    portAttempt: portAttempt,
                    ackAttempt: ackAttempt + 1,
                    generation: activeGeneration
                )
            }
        } else {
            #if DEBUG
            DevLogger.shared.error("[AgentTaskResultWebView \(instanceId)] React ready ack unavailable after init retry window", context: "AgentTaskCapture")
            #endif
        }
    }

    func fadeInWebView() {
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.25
            context.timingFunction = CAMediaTimingFunction(name: .easeIn)
            webView.animator().alphaValue = 1.0
        }
    }
}

