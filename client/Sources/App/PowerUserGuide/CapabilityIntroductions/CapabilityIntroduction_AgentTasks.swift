import SwiftUI

@MainActor
struct CapabilityIntroduction_AgentTasks: View {
    private let bulletSpacing: CGFloat = 6

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                // Header
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .center, spacing: 10) {
                        Image(systemName: "checklist")
                            .font(.system(size: 26))
                            .foregroundColor(AestheticSystem.Colors.primary)
                        Text(BasilTeamIdentity.agentTask.displayName)
                            .font(AestheticSystem.Typography.largeTitle)
                    }

                    Text("Your personal assistant that actually gets things done — just speak and watch it happen")
                        .font(AestheticSystem.Typography.title3)
                        .foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                // How it works
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("It's like having a super-smart assistant").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Press your agentTask hotkey (default: ⌥+Space)")
                        OnboardingBulletStyles.bullet("Tell it what to do: \"Summarize this page\" or \"Write a polite decline email\"")
                        OnboardingBulletStyles.bullet("Basil reads what's on your screen and gets to work")
                        OnboardingBulletStyles.bullet("Watch the results appear live in a handy little panel")
                        OnboardingBulletStyles.bullet("Copy, paste, or tweak — whatever you need")
                    }
                }

                // Why permissions
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("About those permissions").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Microphone: So you can give AgentTasks naturally with your voice")
                        OnboardingBulletStyles.bullet("Accessibility: Lets Basil paste results and do helpful automations")
                    }
                }

                // Practical examples section (NEW)
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Perfect for complex work").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("\"Research this company and draft a personalized outreach email\"")
                        OnboardingBulletStyles.bullet("\"Analyze these meeting notes and create action items\"")
                        OnboardingBulletStyles.bullet("\"Find relevant background on this topic and write a brief\"")
                        OnboardingBulletStyles.bullet("\"Compare these two documents and highlight key differences\"")
                    }
                }

                // When it plans multiple steps (user-friendly wording)
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("For bigger tasks, Basil gets strategic").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Complex requests get broken into smart steps with a clear action plan")
                        OnboardingBulletStyles.bullet("If something's unclear, Basil asks a quick question and keeps going")
                        OnboardingBulletStyles.bullet("You see everything happening in real-time — no mysterious waiting")
                    }
                }

                // Tips
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Tips for best results").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Keep what you want to work with visible on screen when you press the hotkey")
                        OnboardingBulletStyles.bullet("Be specific about style: \"Make it friendly\" or \"Keep it brief\"")
                        OnboardingBulletStyles.bullet("Wake word activation is in development for future hands-free operation")
                    }
                }

                // Adding context with files and folders
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("Add context with files and folders").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Drag files or folders onto the AgentTask widget while speaking")
                        OnboardingBulletStyles.bullet("Dropped items appear as clickable \"References\" below your request")
                        OnboardingBulletStyles.bullet("Say things like \"using these files\" or \"in this folder\" — Basil will know what you mean")
                        OnboardingBulletStyles.bullet("Works for initial AgentTasks and follow-up requests")
                    }
                }

                // Hotkey guidance
                VStack(alignment: .leading, spacing: bulletSpacing) {
                    Text("About the hotkey").font(AestheticSystem.Typography.subheadline).foregroundColor(AestheticSystem.Colors.textPrimary)
                    Group {
                        OnboardingBulletStyles.bullet("Default hotkey: ⌥+Space (Option+Space)")
                        OnboardingBulletStyles.bullet("Choose something comfortable for frequent use")
                        OnboardingBulletStyles.bullet("Customize anytime in Settings → Hotkeys")
                    }
                }
            }
            .padding(32)
        }
    }
}

struct CapabilityIntroduction_AgentTasks_Previews: PreviewProvider {
    static var previews: some View {
        CapabilityIntroduction_AgentTasks()
            .frame(width: 680, height: 520)
    }
}


