import Foundation

struct IOSPairStartResponse: Codable {
    let pairingId: String
    let secret: String
    let expiresAt: String

    enum CodingKeys: String, CodingKey {
        case pairingId = "pairing_id"
        case secret
        case expiresAt = "expires_at"
    }
}

struct IOSPairCompleteRequest: Codable {
    let pairingId: String
    let secret: String
    let deviceId: String
    let deviceName: String

    enum CodingKeys: String, CodingKey {
        case pairingId = "pairing_id"
        case secret
        case deviceId = "device_id"
        case deviceName = "device_name"
    }
}

struct IOSPairCompleteResponse: Codable {
    let deviceId: String
    let deviceName: String
    let token: String
    let issuedAt: String

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case deviceName = "device_name"
        case token
        case issuedAt = "issued_at"
    }
}

struct IOSPairedDevice: Identifiable, Codable {
    var id: String { deviceId }

    let deviceId: String
    let deviceName: String
    let issuedAt: String

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case deviceName = "device_name"
        case issuedAt = "issued_at"
    }
}

extension APIClient {
    func startIOSPairing() async throws -> IOSPairStartResponse {
        let data = try await postForData("/ios-pair/start", EmptyBody())
        return try JSONDecoder().decode(IOSPairStartResponse.self, from: data)
    }

    func completeIOSPairing(_ request: IOSPairCompleteRequest) async throws -> IOSPairCompleteResponse {
        let data = try await postForData("/ios-pair/complete", request)
        return try JSONDecoder().decode(IOSPairCompleteResponse.self, from: data)
    }

    func listIOSPairedDevices(pairToken: String) async throws -> [IOSPairedDevice] {
        var request = URLRequest(url: URL(string: "\(baseURL)/ios-pair/devices")!)
        request.setValue("Bearer \(pairToken)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse, (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }
        return try JSONDecoder().decode([IOSPairedDevice].self, from: data)
    }

    func revokeIOSPairing(deviceId: String, pairToken: String) async throws {
        var request = URLRequest(url: URL(string: "\(baseURL)/ios-pair/revoke")!)
        request.httpMethod = "POST"
        request.setValue("Bearer \(pairToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["device_id": deviceId])
        let (_, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse, (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }
    }
}

