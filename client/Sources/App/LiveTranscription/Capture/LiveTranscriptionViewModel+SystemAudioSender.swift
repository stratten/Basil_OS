import Foundation

extension LiveTranscriptionViewModel {
    /// Builds the off-main sender for system audio. The sender never touches this view model directly; it reports coalesced events, and each handler below hops to the main actor to apply them.
    func makeSystemAudioSender() -> SystemAudioChunkSender {
        SystemAudioChunkSender(
            clock: recordingClock,
            markerMessage: { LiveTranscriptionViewModel.streamClockMarkerMessage(elapsedSeconds: $0) },
            events: SystemAudioChunkSender.Events(
                socketMissing: { [weak self] in
                    Task { @MainActor [weak self] in
                        guard #available(macOS 14.0, *) else { return }
                        guard let self, self.isRecording else { return }
                        #if DEBUG
                        DevLogger.shared.warning("Cannot send system audio chunk: System audio WebSocket not connected", context: "LiveTranscriptionViewModel")
                        #endif
                        if self.connectionState == .recording || self.connectionState == .connecting {
                            self.recoverSystemAudioWebSocket(reason: "socket not connected")
                        }
                    }
                },
                sendFailed: { [weak self] message in
                    // The socket is dead. Recover (debounced) so the stream continues instead of logging failures forever.
                    Task { @MainActor [weak self] in
                        guard #available(macOS 14.0, *) else { return }
                        #if DEBUG
                        DevLogger.shared.error("❌ Failed to send system audio chunk: \(message)", context: "LiveTranscriptionViewModel")
                        #endif
                        self?.recoverSystemAudioWebSocket(reason: "send failed: \(message)")
                    }
                },
                chunksSent: { [weak self] count, lastChunkBytes, sentAt in
                    Task { @MainActor [weak self] in
                        guard #available(macOS 14.0, *) else { return }
                        guard let self else { return }
                        self.lastBufferSendTime = sentAt
                        guard self.systemAudioCaptureMode == .globalOutput else { return }
                        let previousCount = self.systemAudioState?.sentSystemAudioChunkCount ?? 0
                        let nextCount = previousCount + UInt64(count)
                        self.systemAudioState?.sentSystemAudioChunkCount = nextCount
                        #if DEBUG
                        if previousCount == 0 || previousCount / 100 != nextCount / 100 {
                            DevLogger.shared.info(
                                "Global system audio websocket sent chunk \(nextCount) (\(lastChunkBytes) bytes)",
                                context: "LiveTranscriptionViewModel"
                            )
                        }
                        #endif
                    }
                }
            )
        )
    }
}
