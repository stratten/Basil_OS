"""Outlook AppleScript email record templates."""


class OutlookRecordTemplates:
    """Build parser-compatible Outlook email record snippets."""

    def detailed_email_record(self) -> str:
        """Build a detailed Outlook email record with body and recipients."""
        return '''-- Build pipe-separated email data
                        set emailData to ""

                        -- ID
                        try
                            set msgID to id of aMessage as string
                            set emailData to emailData & msgID
                        on error
                            set emailData to emailData & "unknown_id"
                        end try

                        set emailData to emailData & "|||"

                        -- Subject
                        try
                            set msgSubject to subject of aMessage
                            set emailData to emailData & msgSubject
                        on error
                            set emailData to emailData & "No Subject"
                        end try

                        set emailData to emailData & "|||"

                        -- Sender (Outlook returns an email address object, not a string)
                        try
                            set senderObj to sender of aMessage
                            set senderName to name of senderObj
                            set senderAddr to address of senderObj
                            if senderName is not missing value and senderName is not "" then
                                set msgSender to senderName & " <" & senderAddr & ">"
                            else
                                set msgSender to senderAddr
                            end if
                            set emailData to emailData & msgSender
                        on error
                            set emailData to emailData & "Unknown Sender"
                        end try

                        set emailData to emailData & "|||"

                        -- Date sent
                        try
                            set msgDate to time sent of aMessage as string
                            set emailData to emailData & msgDate
                        on error
                            set emailData to emailData & "Unknown Date"
                        end try

                        set emailData to emailData & "|||"

                        -- Email content/body
                        try
                            set msgContent to content of aMessage as string
                            set emailData to emailData & msgContent
                        on error
                            set emailData to emailData & "[No content available]"
                        end try

                        set emailData to emailData & "|||"

                        -- Read status
                        try
                            set msgRead to (is read of aMessage) as string
                            set emailData to emailData & msgRead
                        on error
                            set emailData to emailData & "false"
                        end try

                        set emailData to emailData & "|||"

                        -- TO Recipients
                        try
                            set toRecipients to to recipients of aMessage
                            set toList to {}
                            repeat with aRecipient in toRecipients
                                try
                                    set recipientEmail to email address of aRecipient
                                    if recipientEmail is not missing value and recipientEmail is not "" then
                                        set end of toList to recipientEmail
                                    end if
                                on error
                                    -- Skip invalid recipients
                                end try
                            end repeat
                            set AppleScript's text item delimiters to ","
                            set toRecipientsText to toList as text
                            set AppleScript's text item delimiters to ""
                            set emailData to emailData & toRecipientsText
                        on error
                            set emailData to emailData & ""
                        end try

                        set emailData to emailData & "|||"

                        -- CC Recipients
                        try
                            set ccRecipients to cc recipients of aMessage
                            set ccList to {}
                            repeat with aRecipient in ccRecipients
                                try
                                    set recipientEmail to email address of aRecipient
                                    if recipientEmail is not missing value and recipientEmail is not "" then
                                        set end of ccList to recipientEmail
                                    end if
                                on error
                                    -- Skip invalid recipients
                                end try
                            end repeat
                            set AppleScript's text item delimiters to ","
                            set ccRecipientsText to ccList as text
                            set AppleScript's text item delimiters to ""
                            set emailData to emailData & ccRecipientsText
                        on error
                            set emailData to emailData & ""
                        end try

                        set emailData to emailData & "|||"

                        -- Conversation ID (for thread detection)
                        try
                            set msgConversationID to conversation id of aMessage as string
                            set emailData to emailData & msgConversationID
                        on error
                            set emailData to emailData & ""
                        end try

                        set end of emailList to emailData'''

    def simple_email_record(self) -> str:
        """Build a simplified Outlook record using the enhanced parser format."""
        return '''set emailData to ""

                            -- ID
                            try
                                set emailData to emailData & (id of aMessage as string)
                            on error
                                set emailData to emailData & "unknown_id"
                            end try
                            set emailData to emailData & "|||"

                            -- Subject
                            try
                                set emailData to emailData & (subject of aMessage)
                            on error
                                set emailData to emailData & "No Subject"
                            end try
                            set emailData to emailData & "|||"

                            -- Sender
                            try
                                set senderObj to sender of aMessage
                                set senderName to name of senderObj
                                set senderAddr to address of senderObj
                                if senderName is not missing value and senderName is not "" then
                                    set emailData to emailData & senderName & " <" & senderAddr & ">"
                                else
                                    set emailData to emailData & senderAddr
                                end if
                            on error
                                set emailData to emailData & "Unknown Sender"
                            end try
                            set emailData to emailData & "|||"

                            -- Date sent
                            try
                                set emailData to emailData & (time sent of aMessage as string)
                            on error
                                set emailData to emailData & "Unknown Date"
                            end try
                            set emailData to emailData & "|||"

                            -- Content
                            try
                                set emailData to emailData & (content of aMessage as string)
                            on error
                                set emailData to emailData & "[No content available]"
                            end try
                            set emailData to emailData & "|||"

                            -- Read status
                            try
                                set emailData to emailData & ((is read of aMessage) as string)
                            on error
                                set emailData to emailData & "false"
                            end try
                            set emailData to emailData & "|||"

                            -- TO (empty for simple variant)
                            set emailData to emailData & ""
                            set emailData to emailData & "|||"

                            -- CC (empty for simple variant)
                            set emailData to emailData & ""
                            set emailData to emailData & "|||"

                            -- Conversation ID (for thread detection)
                            try
                                set emailData to emailData & (conversation id of aMessage as string)
                            on error
                                set emailData to emailData & ""
                            end try

                            set end of emailList to emailData'''

    def metadata_email_record(self) -> str:
        """Build an Outlook metadata record without reading message body content."""
        return '''set emailData to ""

                            try
                                set emailData to emailData & (id of aMessage as string)
                            on error
                                set emailData to emailData & "unknown_id"
                            end try
                            set emailData to emailData & "|||"

                            try
                                set emailData to emailData & (subject of aMessage)
                            on error
                                set emailData to emailData & "No Subject"
                            end try
                            set emailData to emailData & "|||"

                            try
                                set senderObj to sender of aMessage
                                set senderName to name of senderObj
                                set senderAddr to address of senderObj
                                if senderName is not missing value and senderName is not "" then
                                    set emailData to emailData & senderName & " <" & senderAddr & ">"
                                else
                                    set emailData to emailData & senderAddr
                                end if
                            on error
                                set emailData to emailData & "Unknown Sender"
                            end try
                            set emailData to emailData & "|||"

                            try
                                set emailData to emailData & (time received of aMessage as string)
                            on error
                                try
                                    set emailData to emailData & (time sent of aMessage as string)
                                on error
                                    set emailData to emailData & "Unknown Date"
                                end try
                            end try
                            set emailData to emailData & "|||"

                            set emailData to emailData & ""
                            set emailData to emailData & "|||"

                            try
                                set emailData to emailData & ((is read of aMessage) as string)
                            on error
                                set emailData to emailData & "false"
                            end try
                            set emailData to emailData & "|||"

                            set emailData to emailData & ""
                            set emailData to emailData & "|||"

                            set emailData to emailData & ""
                            set emailData to emailData & "|||"

                            try
                                set emailData to emailData & (conversation id of aMessage as string)
                            on error
                                set emailData to emailData & ""
                            end try
                            set emailData to emailData & "|||"

                            try
                                set emailData to emailData & ((todo flag of aMessage) as string)
                            on error
                                set emailData to emailData & "false"
                            end try

                            set end of emailList to emailData'''
