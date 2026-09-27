import AppKit
@preconcurrency import WebKit

extension SettingsShellWindowController {
    func wireProfileSettingsWebView(_ profileWebView: ReactProfileSettingsWebView) {
        profileWebView.onReady = { [weak self] in
            Task { @MainActor in
                await self?.loadProfileSettingsAndSendInit()
            }
        }
        profileWebView.onSaveProfile = { [weak self] requestId, fields in
            Task { @MainActor in
                await self?.saveProfileFields(requestId: requestId, fields: fields)
            }
        }
        profileWebView.onRequestClearProfile = { [weak self] requestId in
            Task { @MainActor in
                await self?.presentClearProfileConfirmation(requestId: requestId)
            }
        }
    }

    private func loadProfileSettingsAndSendInit() async {
        guard let profileWebView else { return }
        do {
            let profile = try await APIClient.shared.getUserProfile()
            profileWebView.sendInit(profile: profile)
        } catch {
            profileWebView.sendLoadError(message: "Failed to load Profile settings.")
        }
    }

    private func saveProfileFields(requestId: String, fields: ReactProfileFieldsPayload) async {
        guard let profileWebView else { return }
        let profileData = UserProfileCreate(
            full_name: fields.fullName,
            preferred_name: fields.preferredName,
            email: fields.email,
            job_title: fields.jobTitle,
            company_name: fields.companyName,
            industry: fields.industry,
            default_formality: fields.formality,
            default_tone: fields.tone,
            custom_instructions: fields.customInstructions
        )
        do {
            let updatedProfile = try await APIClient.shared.saveUserProfile(profileData)
            profileWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
            profileWebView.sendSnapshot(profile: updatedProfile)
        } catch {
            profileWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to save profile.")
        }
    }

    private func presentClearProfileConfirmation(requestId: String) async {
        guard let profileWebView else { return }
        let alert = Self.makeClearProfileConfirmationAlert()

        guard alert.runModal() == .alertSecondButtonReturn else {
            profileWebView.sendIntentResult(requestId: requestId, status: "cancelled", message: nil)
            return
        }

        do {
            try await APIClient.shared.deleteUserProfile()
            let clearedProfile = UserProfile(
                id: "default",
                full_name: nil,
                preferred_name: nil,
                email: nil,
                job_title: nil,
                company_name: nil,
                industry: nil,
                default_formality: nil,
                default_tone: nil,
                custom_instructions: nil,
                created_at: nil,
                updated_at: nil,
                profile_version: nil
            )
            profileWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
            profileWebView.sendSnapshot(profile: clearedProfile)
        } catch {
            profileWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to delete profile data.")
        }
    }

    static func makeClearProfileConfirmationAlert() -> NSAlert {
        let alert = NSAlert()
        alert.messageText = "Delete All Personalization Data?"
        alert.informativeText = "This permanently deletes your profile, writing samples, communication style, and contact relationships. This cannot be undone."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Cancel")
        let deleteButton = alert.addButton(withTitle: "Delete Everything")
        deleteButton.hasDestructiveAction = true
        return alert
    }
}
