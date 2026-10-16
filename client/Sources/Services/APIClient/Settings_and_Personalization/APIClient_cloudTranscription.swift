import Foundation

/// The result of one cloud meeting transcription request: the backend's JSON object, or a message that is safe to show the user.
enum CloudTranscriptionOutcome {
    case success([String: Any])
    case failure(String)

    /// Turns an HTTP status and body into an outcome, reading the backend's `detail` message when it sent one.
    static func decode(statusCode: Int, data: Data) -> CloudTranscriptionOutcome {
        let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        guard (200...299).contains(statusCode) else {
            if let detail = object?["detail"] as? String, !detail.isEmpty {
                return .failure(detail)
            }
            if statusCode == 422 {
                return .failure("Basil did not accept that value. Check it and try again.")
            }
            return .failure("The cloud transcription request failed (status \(statusCode)).")
        }
        guard let object else {
            return .failure("Basil returned a response that could not be read.")
        }
        return .success(object)
    }
}

extension APIClient {
    /// Sends one request to the `/meetings/cloud-transcription` routes and returns the backend's JSON object or a user-facing failure.
    func sendCloudTranscriptionRequest(method: String, path: String, body: [String: Any]? = nil) async -> CloudTranscriptionOutcome {
        if !isBackendAvailable { await updatePortAndCheckStatus() }
        guard isBackendAvailable else {
            return .failure("Basil is not running yet. Try again in a moment.")
        }
        guard let url = URL(string: baseURL + "/meetings/cloud-transcription" + path) else {
            return .failure("The cloud transcription address is not valid.")
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 30
        if let body {
            guard let encoded = try? JSONSerialization.data(withJSONObject: body) else {
                return .failure("The request could not be prepared.")
            }
            request.httpBody = encoded
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return .failure("Basil returned a response that could not be read.")
            }
            return CloudTranscriptionOutcome.decode(statusCode: http.statusCode, data: data)
        } catch {
            return .failure("Could not reach Basil: \(error.localizedDescription)")
        }
    }
}
