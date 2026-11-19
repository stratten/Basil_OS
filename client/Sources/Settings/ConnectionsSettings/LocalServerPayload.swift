import Foundation

enum LocalServerPayload {
    /// The `localServer` object for one connection's snapshot, or nil for a connection that is not a program on this Mac. `isSecretSaved` receives the Keychain account of one secret.
    static func payload(
        for details: APIClient.LocalServerDetails?,
        connectionId: String,
        isSecretSaved: (String) -> Bool
    ) -> [String: Any]? {
        guard let details else { return nil }

        func secrets(_ names: [String]) -> [[String: Any]] {
            names.map { name in
                [
                    "name": name,
                    "saved": isSecretSaved(LocalServerSecretKey.account(connectionId: connectionId, name: name)),
                ]
            }
        }

        let companion: [String: Any]? = details.companion.map { status in
            var fields: [String: Any] = [
                "status": status.status,
                "port": status.port as Any,
                "lastError": status.lastError as Any,
                "logTail": status.logTail,
                "restartCount": status.restartCount,
                "startWithBasil": status.startWithBasil,
                "fixedPort": status.fixedPort as Any,
                "secretEnv": secrets(status.secretEnv),
                "commandSummary": status.commandSummary,
                "hasProbe": status.hasProbe ?? false,
            ]
            if let phase = status.healthPhase {
                fields["health"] = [
                    "phase": phase,
                    "message": status.healthMessage ?? "",
                    "actionKind": status.actionKind as Any,
                    "actionValue": status.actionValue as Any,
                    "actionExpiresAt": status.actionExpiresAt as Any,
                ] as [String: Any]
            }
            return fields
        }
        return [
            "commandSummary": details.commandSummary,
            "sourceUrl": details.sourceUrl as Any,
            "secretEnv": secrets(details.secretEnv),
            "companion": companion as Any,
            "install": details.install.map(installPayload) as Any,
        ]
    }

    /// The `install` object for a server added with a setup recipe. Every address, hash, commit and command is carried in full, because Settings shows them before the person chooses anything.
    static func installPayload(_ install: APIClient.LocalServerInstallStatus) -> [String: Any] {
        [
            "phase": install.phase,
            "message": install.message,
            "ready": install.ready,
            "active": install.active,
            "artifact": install.artifact as Any,
            "requirement": install.requirement as Any,
            "canInstall": install.canInstall,
            "detail": install.detail as Any,
            "requirements": install.requirements.map { requirement in
                [
                    "name": requirement.name,
                    "reason": requirement.reason,
                    "forMethod": requirement.forMethod,
                    "installCommand": requirement.installCommand as Any,
                ] as [String: Any]
            },
            "artifacts": install.artifacts.map { artifact in
                [
                    "name": artifact.name,
                    "expects": artifact.expects,
                    "ready": artifact.ready,
                    "sources": artifact.sources,
                ] as [String: Any]
            },
        ]
    }
}
