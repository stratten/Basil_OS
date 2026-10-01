import AppKit
import Foundation

enum ExecutionApprovalRiskConfirmationError: LocalizedError, Equatable {
    case declined

    var errorDescription: String? {
        "The change was not confirmed."
    }
}

struct ExecutionApprovalRiskPrompt: Equatable {
    let title: String
    let message: String
}

/// Turns the backend's risk-confirmation response into an explicit native confirmation.
enum ExecutionApprovalRiskConfirmation {
    static let confirmationHeader = "X-Basil-Risk-Confirmed"
    static let confirmationRequiredStatus = 428
    static let confirmationRequiredCode = "risk_confirmation_required"

    @MainActor
    static var presenter: (ExecutionApprovalRiskPrompt) -> Bool = presentAlert

    private struct ConfirmationRequiredBody: Decodable {
        struct Detail: Decodable {
            let code: String
            let title: String
            let message: String
        }

        let detail: Detail
    }

    static func confirmationPrompt(statusCode: Int, data: Data) -> ExecutionApprovalRiskPrompt? {
        guard statusCode == confirmationRequiredStatus,
              let body = try? JSONDecoder().decode(ConfirmationRequiredBody.self, from: data),
              body.detail.code == confirmationRequiredCode,
              !body.detail.title.isEmpty,
              !body.detail.message.isEmpty else {
            return nil
        }
        return ExecutionApprovalRiskPrompt(title: body.detail.title, message: body.detail.message)
    }

    static func send(_ request: URLRequest, session: URLSession = .shared) async throws -> (Data, URLResponse) {
        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse,
              let prompt = confirmationPrompt(statusCode: httpResponse.statusCode, data: data) else {
            return (data, response)
        }
        let approved = await MainActor.run { presenter(prompt) }
        guard approved else {
            throw ExecutionApprovalRiskConfirmationError.declined
        }
        var confirmedRequest = request
        confirmedRequest.setValue("true", forHTTPHeaderField: confirmationHeader)
        return try await session.data(for: confirmedRequest)
    }

    @MainActor
    static func presentAlert(_ prompt: ExecutionApprovalRiskPrompt) -> Bool {
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = prompt.title
        alert.informativeText = prompt.message
        alert.addButton(withTitle: "Cancel")
        alert.addButton(withTitle: "Allow")
        NSApp.activate(ignoringOtherApps: true)
        return alert.runModal() == .alertSecondButtonReturn
    }
}

extension APIClient {
    func postConfirmingExecutionApprovalRisk(_ endpoint: String, body: Data) async throws -> Data {
        guard let url = URL(string: "\(baseURL)\(endpoint)") else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 120
        let (data, response) = try await ExecutionApprovalRiskConfirmation.send(request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        if httpResponse.statusCode >= 400 {
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }
        return data
    }
}
