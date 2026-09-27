import SwiftUI

@MainActor
struct CapabilityIntroduction_Conversation: View {
    private let bulletSpacing: CGFloat = 6

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                // Header
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .center, spacing: 10) {
                        Image(systemName: "bubble.left.and.bubble.right.fill")
                            .font(.system(size: 26))
                            .foregroundColor(AestheticSystem.Colors.primary)
                        Text("Conversation")
                            .font(AestheticSystem.Typography.largeTitle)
                    }

                    Text("Your assistantSession AI chat — iterate, refine, and explore ideas")
                        .font(AestheticSystem.Typography.title3)
                        .foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                // What makes it unique
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("What makes it special").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Switch AI models mid-conversation — compare responses or use the best model for each task")
                        OnboardingBulletStyles.bullet("Persistent chat history lets you iterate and build on previous exchanges")
                        OnboardingBulletStyles.bullet("Streaming responses so you see progress in real-time")
                        OnboardingBulletStyles.bullet("Press your conversation hotkey (default: F8) to open the chat panel anytime")
                    }
                }

                // Key details
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Good to know").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("No special permissions needed — just keyboard and mouse")
                        OnboardingBulletStyles.bullet("You control what the AI sees by pasting or typing content")
                        OnboardingBulletStyles.bullet("Conversation history stays local and private")
                    }
                }

                // When to use
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Best for").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Iterating on drafts: \"Make this more formal\" → \"Now shorter\" → \"Perfect!\"")
                        OnboardingBulletStyles.bullet("Exploring ideas through back-and-forth discussion")
                        OnboardingBulletStyles.bullet("Working with pasted content when you don't need screen context")
                        OnboardingBulletStyles.bullet("Comparing different AI model responses on the same question")
                    }
                }

                // Hotkey guidance
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("About the hotkey").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Default hotkey: F8")
                        OnboardingBulletStyles.bullet("Opens the chat panel instantly from anywhere")
                        OnboardingBulletStyles.bullet("Customize anytime in Settings → Hotkeys")
                    }
                }
            }
            .padding(32)
        }
    }
}

struct CapabilityIntroduction_Conversation_Previews: PreviewProvider {
    static var previews: some View {
        CapabilityIntroduction_Conversation()
            .frame(width: 680, height: 520)
    }
}
