import Foundation

extension WebSocketService {
    private static var maximumReconnectDelaySeconds: UInt64 { 30 }

    func connect() {
        guard webSocket == nil, !isReconnecting else {
            print("WebSocket connect called but connection exists or is reconnecting")
            return
        }

        guard let url = URL(string: "\(apiBaseURL)/ws") else {
            print("Failed to create WebSocket URL")
            return
        }

        print("\n🔌 Creating new WebSocket connection to \(url)")
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 0  // No timeout
        configuration.timeoutIntervalForResource = 0  // No timeout
        session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        webSocket = session?.webSocketTask(with: url)

        webSocket?.resume()
        receiveMessage()
        // Removed duplicate receive loop to avoid race conditions that drop messages
        // transcription.receiveTranscriptionMessages()
        startPingTimer()
    }

    // Update the WebSocket delegate to handle meeting connections
    nonisolated func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) {
        Task { @MainActor in
            if webSocketTask == self.webSocket {
                print("Main WebSocket connected successfully")
                reconnectAttempt = 0
                isReconnecting = false
                isConnected = true
                eventSubject.send(.connectionStateChanged(true))
            } // (Meeting WebSocket handling removed)
        }
    }

    nonisolated func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        Task { @MainActor in
            if webSocketTask == self.webSocket {
                print("Main WebSocket closed with code: \(closeCode)")
                isConnected = false
                eventSubject.send(.connectionStateChanged(false))
                onClose?()

                // Attempt reconnect if not a normal closure
                if closeCode != .normalClosure {
                    await handleDisconnect()
                }
            } // (Meeting WebSocket close handling removed)
        }
    }

    func startPingTimer() {
        pingTimer?.invalidate()
        pingTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            Task { @MainActor in
                try? await self?.sendPing()
            }
        }
    }

    func stopPingTimer() {
        pingTimer?.invalidate()
        pingTimer = nil
    }

    func sendPing() async throws {
        guard let webSocket else {
            throw WebSocketError.notConnected
        }

        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            webSocket.sendPing { [weak self] error in
                if let error = error {
                    print("WebSocket ping failed: \(error)")
                    Task { @MainActor [weak self] in
                        await self?.handleDisconnect()
                    }
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume()
                }
            }
        }
    }

    func handleDisconnect() async {
        print("Handling disconnect - Current state: connected=\(isConnected), reconnecting=\(isReconnecting)")

        guard isConnected || webSocket != nil else {
            print("Already disconnected, no need to handle disconnect")
            isConnected = false
            stopPingTimer()
            return
        }

        isConnected = false
        stopPingTimer()

        if webSocket?.state != .canceling && webSocket?.state != .completed {
            webSocket?.cancel()
        }
        webSocket = nil
        session?.invalidateAndCancel()
        session = nil

        guard reconnectTask == nil else { return }
        isReconnecting = true
        eventSubject.send(.connectionStateChanged(false))

        reconnectTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                self.reconnectTask = nil
            }

            let delaySeconds = min(
                UInt64(1 << min(self.reconnectAttempt, 5)),
                Self.maximumReconnectDelaySeconds
            )
            self.reconnectAttempt += 1

            do {
                try await Task.sleep(nanoseconds: delaySeconds * 1_000_000_000)
                try Task.checkCancellation()
                self.isReconnecting = false
                print("Attempting reconnection after \(delaySeconds)s delay...")
                self.connect()
            } catch {
                print("Reconnection attempt cancelled or failed: \(error)")
                self.isReconnecting = false
            }
        }
    }
}
