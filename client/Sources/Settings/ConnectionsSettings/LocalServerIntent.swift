import Foundation

/// One of the nine requests the Connections web page can make about a program on this Mac.
enum LocalServerIntent: Equatable {
    case register(requestId: String, registration: APIClient.LocalServerRegistration, secretValues: [String: String])
    case startCompanion(requestId: String, connectionId: String)
    case stopCompanion(requestId: String, connectionId: String)
    case setStartWithBasil(requestId: String, connectionId: String, enabled: Bool)
    case saveSecrets(requestId: String, connectionId: String, secretValues: [String: String])
    case refreshStatus(requestId: String, connectionId: String)
    case prepare(requestId: String, connectionId: String)
    case cancelPrepare(requestId: String, connectionId: String)
    case installRequirement(requestId: String, connectionId: String, name: String, command: String)
}

extension LocalServerIntent: CustomStringConvertible {
    /// Names only. A secret value must never appear in a log line or a debugger description.
    var description: String {
        switch self {
        case .register(let requestId, let registration, let secretValues):
            return "register(requestId: \(requestId), name: \(registration.friendlyName), secretNames: \(secretValues.keys.sorted()))"
        case .startCompanion(let requestId, let connectionId):
            return "startCompanion(requestId: \(requestId), connectionId: \(connectionId))"
        case .stopCompanion(let requestId, let connectionId):
            return "stopCompanion(requestId: \(requestId), connectionId: \(connectionId))"
        case .setStartWithBasil(let requestId, let connectionId, let enabled):
            return "setStartWithBasil(requestId: \(requestId), connectionId: \(connectionId), enabled: \(enabled))"
        case .saveSecrets(let requestId, let connectionId, let secretValues):
            return "saveSecrets(requestId: \(requestId), connectionId: \(connectionId), secretNames: \(secretValues.keys.sorted()))"
        case .refreshStatus(let requestId, let connectionId):
            return "refreshStatus(requestId: \(requestId), connectionId: \(connectionId))"
        case .prepare(let requestId, let connectionId):
            return "prepare(requestId: \(requestId), connectionId: \(connectionId))"
        case .cancelPrepare(let requestId, let connectionId):
            return "cancelPrepare(requestId: \(requestId), connectionId: \(connectionId))"
        case .installRequirement(let requestId, let connectionId, let name, let command):
            return "installRequirement(requestId: \(requestId), connectionId: \(connectionId), name: \(name), command: \(command))"
        }
    }
}

enum LocalServerIntentParsing {
    static let messageTypes: Set<String> = [
        "requestRegisterLocalServer",
        "requestStartCompanion",
        "requestStopCompanion",
        "requestSetCompanionStartWithBasil",
        "requestSaveLocalServerSecrets",
        "requestRefreshLocalServerStatus",
        "requestPrepareLocalServer",
        "requestCancelPrepareLocalServer",
        "requestInstallLocalServerRequirement",
    ]

    static func intent(type: String, body: [String: Any]) -> LocalServerIntent? {
        guard let requestId = body["requestId"] as? String else { return nil }
        switch type {
        case "requestRegisterLocalServer":
            guard let registrationBody = body["registration"] as? [String: Any],
                  let registration = registration(from: registrationBody),
                  let secretValues = body["secretValues"] as? [String: String] else {
                return nil
            }
            return .register(requestId: requestId, registration: registration, secretValues: secretValues)
        case "requestStartCompanion":
            guard let connectionId = body["connectionId"] as? String else { return nil }
            return .startCompanion(requestId: requestId, connectionId: connectionId)
        case "requestStopCompanion":
            guard let connectionId = body["connectionId"] as? String else { return nil }
            return .stopCompanion(requestId: requestId, connectionId: connectionId)
        case "requestSetCompanionStartWithBasil":
            guard let connectionId = body["connectionId"] as? String,
                  let enabled = (body["startWithBasil"] as? NSNumber)?.boolValue else {
                return nil
            }
            return .setStartWithBasil(requestId: requestId, connectionId: connectionId, enabled: enabled)
        case "requestSaveLocalServerSecrets":
            guard let connectionId = body["connectionId"] as? String,
                  let secretValues = body["secretValues"] as? [String: String] else {
                return nil
            }
            return .saveSecrets(requestId: requestId, connectionId: connectionId, secretValues: secretValues)
        case "requestRefreshLocalServerStatus":
            guard let connectionId = body["connectionId"] as? String else { return nil }
            return .refreshStatus(requestId: requestId, connectionId: connectionId)
        case "requestPrepareLocalServer":
            guard let connectionId = body["connectionId"] as? String else { return nil }
            return .prepare(requestId: requestId, connectionId: connectionId)
        case "requestCancelPrepareLocalServer":
            guard let connectionId = body["connectionId"] as? String else { return nil }
            return .cancelPrepare(requestId: requestId, connectionId: connectionId)
        case "requestInstallLocalServerRequirement":
            guard let connectionId = body["connectionId"] as? String,
                  let name = body["name"] as? String,
                  let command = body["command"] as? String else {
                return nil
            }
            return .installRequirement(requestId: requestId, connectionId: connectionId, name: name, command: command)
        default:
            return nil
        }
    }

    static func registration(from body: [String: Any]) -> APIClient.LocalServerRegistration? {
        guard let friendlyName = body["friendlyName"] as? String,
              let command = body["command"] as? String,
              let args = body["args"] as? [String],
              let env = body["env"] as? [String: String],
              let secretEnv = body["secretEnv"] as? [String] else {
            return nil
        }
        var companion: APIClient.LocalServerCompanionRegistration?
        if let companionValue = body["companion"], !(companionValue is NSNull) {
            guard let companionBody = companionValue as? [String: Any],
                  let parsed = companionRegistration(from: companionBody) else {
                return nil
            }
            companion = parsed
        }
        var install: LocalServerJSONValue?
        if let installValue = body["install"], !(installValue is NSNull) {
            guard installValue is [String: Any], let parsed = LocalServerJSONValue(any: installValue) else { return nil }
            install = parsed
        }
        return APIClient.LocalServerRegistration(
            friendlyName: friendlyName,
            description: nonBlank(body["description"]),
            command: command,
            args: args,
            cwd: nonBlank(body["cwd"]),
            env: env,
            sourceUrl: nonBlank(body["sourceUrl"]),
            secretEnv: secretEnv,
            companion: companion,
            connectionId: nil,
            install: install
        )
    }

    static func companionRegistration(from body: [String: Any]) -> APIClient.LocalServerCompanionRegistration? {
        guard let command = body["command"] as? String,
              let args = body["args"] as? [String],
              let env = body["env"] as? [String: String],
              let secretEnv = body["secretEnv"] as? [String],
              let startWithBasil = (body["startWithBasil"] as? NSNumber)?.boolValue else {
            return nil
        }
        var probe: LocalServerJSONValue?
        if let probeValue = body["probe"], !(probeValue is NSNull) {
            guard probeValue is [String: Any], let parsed = LocalServerJSONValue(any: probeValue) else { return nil }
            probe = parsed
        }
        return APIClient.LocalServerCompanionRegistration(
            command: command,
            args: args,
            cwd: nonBlank(body["cwd"]),
            env: env,
            secretEnv: secretEnv,
            startWithBasil: startWithBasil,
            fixedPort: (body["fixedPort"] as? NSNumber)?.intValue,
            probe: probe
        )
    }

    private static func nonBlank(_ value: Any?) -> String? {
        guard let text = value as? String else { return nil }
        return text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : text
    }
}
