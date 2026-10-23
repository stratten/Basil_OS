import Foundation
import AppKit
import HotKey

// MARK: - Models

/// Response wrapper for hotkey settings from the backend
struct ServerHotkeySettingsResponse: Codable {
    let settings: ServerHotkeySettings
}

/// Individual hotkey settings structure.
///
/// `get_suggestions` (legacy F9 basic suggestion) and `enhanced_suggestions`
/// (legacy F10 XML-parsed suggestion) were removed as part of the AssistantSession
/// unification. Both modalities now live behind the unified
/// `assistantSession` hotkey with an in-widget speak/type toggle.
struct ServerHotkeySettings: Codable {
    let capture_screen: HotkeyBinding
    let transcribe_audio: HotkeyBinding
    let streaming_transcription: HotkeyBinding
    let conversation_toggle: HotkeyBinding
    let insert_assistant_output: HotkeyBinding
    let assistantSession: HotkeyBinding
    let agentTask: HotkeyBinding
    let home_board_toggle: HotkeyBinding

    enum CodingKeys: String, CodingKey {
        case capture_screen
        case transcribe_audio
        case streaming_transcription
        case conversation_toggle
        case insert_assistant_output
        case assistantSession = "assistant_session"
        case agentTask = "agent_task"
        case home_board_toggle
    }
}

extension NSEvent.ModifierFlags {
    init(modifiers: [String]) {
        self.init()
        for modifier in modifiers {
            switch modifier.lowercased() {
            case "cmd", "command": insert(.command)
            case "ctrl", "control": insert(.control)
            case "alt", "option": insert(.option)
            case "shift": insert(.shift)
            case "fn": insert(.function)
            default: break
            }
        }
    }
}

extension Key {
    init?(string: String) {
        switch string.lowercased() {
        case "f1": self = .f1
        case "f2": self = .f2
        case "f3": self = .f3
        case "f4": self = .f4
        case "f5": self = .f5
        case "f6": self = .f6
        case "f7": self = .f7
        case "f8": self = .f8
        case "f9": self = .f9
        case "f10": self = .f10
        case "f11": self = .f11
        case "f12": self = .f12
        case "space": self = .space
        case "return", "enter": self = .return
        case "tab": self = .tab
        case "escape", "esc": self = .escape
        case "delete", "backspace": self = .delete
        case "up": self = .upArrow
        case "down": self = .downArrow
        case "left": self = .leftArrow
        case "right": self = .rightArrow
        case let single where single.count == 1:
            // Handle single character keys (a-z, 0-9, etc.)
            let char = single.uppercased().first!
            switch char {
            case "A": self = .a
            case "B": self = .b
            case "C": self = .c
            case "D": self = .d
            case "E": self = .e
            case "F": self = .f
            case "G": self = .g
            case "H": self = .h
            case "I": self = .i
            case "J": self = .j
            case "K": self = .k
            case "L": self = .l
            case "M": self = .m
            case "N": self = .n
            case "O": self = .o
            case "P": self = .p
            case "Q": self = .q
            case "R": self = .r
            case "S": self = .s
            case "T": self = .t
            case "U": self = .u
            case "V": self = .v
            case "W": self = .w
            case "X": self = .x
            case "Y": self = .y
            case "Z": self = .z
            case "0": self = .zero
            case "1": self = .one
            case "2": self = .two
            case "3": self = .three
            case "4": self = .four
            case "5": self = .five
            case "6": self = .six
            case "7": self = .seven
            case "8": self = .eight
            case "9": self = .nine
            case "`": self = .grave
            case "-": self = .minus
            case "=": self = .equal
            case "[": self = .leftBracket
            case "]": self = .rightBracket
            case "\\": self = .backslash
            case ";": self = .semicolon
            case "'": self = .quote
            case ",": self = .comma
            case ".": self = .period
            case "/": self = .slash
            case " ": self = .space
            default: return nil
            }
        default: return nil
        }
    }
}

// `SuggestionResponse` and its `DynamicCodingKeys` helper used to live
// here -- they decoded the legacy `/hotkeys/suggestions/process_captured_image`
// XML-metadata payload consumed by the deleted `HotkeyHandler_Suggestions`
// surface. Unreferenced after the AssistantSession unification removed both the
// route and the handler.
