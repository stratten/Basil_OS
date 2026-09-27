from time import time
from typing import Optional, List, Tuple, Union, Any

from whisper_live_core.timed_objects import Line, SilentLine, ASRToken, SpeakerSegment, Silence, TimedText, Segment


class TokensAlignment:

    def __init__(self, state: Any, args: Any, sep: Optional[str]) -> None:
        self.state = state
        self.diarization = args.diarization
        self._tokens_index: int = 0
        self._diarization_index: int = 0
        self._translation_index: int = 0

        self.all_tokens: List[ASRToken] = []
        self.all_diarization_segments: List[SpeakerSegment] = []
        self.all_translation_segments: List[Any] = []

        self.new_tokens: List[ASRToken] = []
        self.new_diarization: List[SpeakerSegment] = []
        self.new_translation: List[Any] = []
        self.new_translation_buffer: Union[TimedText, str] = TimedText()
        self.new_tokens_buffer: List[Any] = []
        self.sep: str = sep if sep is not None else ' '
        self.beg_loop: Optional[float] = None

        # Track how many lines we've sent to avoid re-sending
        self._last_sent_line_count: int = 0
        
        # Track which lines have been sent to avoid re-sending entire transcript
        self._last_sent_line_count: int = 0

    def update(self) -> None:
        """Drain state buffers into the running alignment context."""
        self.new_tokens, self.state.new_tokens = self.state.new_tokens, []
        self.new_diarization, self.state.new_diarization = self.state.new_diarization, []
        self.new_translation, self.state.new_translation = self.state.new_translation, []
        self.new_tokens_buffer, self.state.new_tokens_buffer = self.state.new_tokens_buffer, []

        self.all_tokens.extend(self.new_tokens)
        self.all_diarization_segments.extend(self.new_diarization)
        self.all_translation_segments.extend(self.new_translation)
        self.new_translation_buffer = self.state.new_translation_buffer
        
        # Track the new token text for incremental sending (filter out Silence objects)
        self._new_token_text = self.sep.join([t.text for t in self.new_tokens if not t.is_silence()]) if self.new_tokens else ""

    def add_translation(self, line: Line) -> None:
        """Append translated text segments that overlap with a line."""
        for ts in self.all_translation_segments:
            if ts.is_within(line):
                line.translation += ts.text + (self.sep if ts.text else '')
            elif line.translation:
                break


    def compute_punctuations_segments(self, tokens: Optional[List[ASRToken]] = None) -> List[Segment]:
        """Group tokens into segments split by punctuation and explicit silence."""
        segments = []
        segment_start_idx = 0
        for i, token in enumerate(self.all_tokens):
            if token.is_silence():
                previous_segment = Segment.from_tokens(
                        tokens=self.all_tokens[segment_start_idx: i],
                    )
                if previous_segment:
                    segments.append(previous_segment)
                segment = Segment.from_tokens(
                    tokens=[token],
                    is_silence=True
                )
                segments.append(segment)
                segment_start_idx = i+1
            else:
                if token.has_punctuation():
                    segment = Segment.from_tokens(
                        tokens=self.all_tokens[segment_start_idx: i+1],
                    )
                    segments.append(segment)
                    segment_start_idx = i+1

        final_segment = Segment.from_tokens(
            tokens=self.all_tokens[segment_start_idx:],
        )
        if final_segment:
            segments.append(final_segment)
        return segments


    def concatenate_diar_segments(self) -> List[SpeakerSegment]:
        """Merge consecutive diarization slices that share the same speaker."""
        if not self.all_diarization_segments:
            return []
        merged = [self.all_diarization_segments[0]]
        for segment in self.all_diarization_segments[1:]:
            if segment.speaker == merged[-1].speaker:
                merged[-1].end = segment.end
            else:
                merged.append(segment)
        return merged


    @staticmethod
    def intersection_duration(seg1: TimedText, seg2: TimedText) -> float:
        """Return the overlap duration between two timed segments."""
        start = max(seg1.start, seg2.start)
        end = min(seg1.end, seg2.end)

        return max(0, end - start)

    def get_lines_diarization(self) -> Tuple[List[Line], str]:
        """Build lines when diarization is enabled and track overflow buffer."""
        diarization_buffer = ''
        punctuation_segments = self.compute_punctuations_segments()
        diarization_segments = self.concatenate_diar_segments()
        for punctuation_segment in punctuation_segments:
            if not punctuation_segment.is_silence():
                if diarization_segments and punctuation_segment.start >= diarization_segments[-1].end:
                    diarization_buffer += punctuation_segment.text
                else:
                    max_overlap = 0.0
                    max_overlap_speaker = diarization_segments[0].speaker if diarization_segments else "speaker0"
                    for diarization_segment in diarization_segments:
                        intersec = self.intersection_duration(punctuation_segment, diarization_segment)
                        if intersec > max_overlap:
                            max_overlap = intersec
                            max_overlap_speaker = diarization_segment.speaker
                    
                    # Normalize speaker ID to string or None
                    if isinstance(max_overlap_speaker, int):
                        # -1 = unknown, -2 = silence -> None
                        if max_overlap_speaker < 0:
                            max_overlap_speaker = None
                        else:
                            # Convert 0 -> "speaker0", 1 -> "speaker1", etc.
                            max_overlap_speaker = f"speaker{max_overlap_speaker}"
                    # If it's already a string, use it as-is (diart format)
                    # If it's None, keep it None
                    
                    punctuation_segment.speaker = max_overlap_speaker
        
        lines = []
        if punctuation_segments:
            lines = [Line().build_from_segment(punctuation_segments[0])]
            for segment in punctuation_segments[1:]:
                if segment.speaker == lines[-1].speaker:
                    if lines[-1].text:
                        lines[-1].text += segment.text
                    lines[-1].end = segment.end
                else:
                    lines.append(Line().build_from_segment(segment))

        return lines, diarization_buffer


    def get_lines(
            self, 
            diarization: bool = False,
            translation: bool = False,
            current_silence: Optional[Silence] = None
        ) -> Tuple[List[Line], str, Union[str, TimedText]]:
        """Return the formatted lines plus buffers, optionally with diarization/translation."""
        if diarization:
            all_lines, diarization_buffer = self.get_lines_diarization()
            has_in_progress_line = False  # Diarization doesn't track this the same way
        else:
            diarization_buffer = ''
            all_lines = []
            current_line_tokens = []
            for token in self.all_tokens:
                if token.is_silence():
                    if current_line_tokens:
                        all_lines.append(Line().build_from_tokens(current_line_tokens))
                        current_line_tokens = []
                    end_silence = token.end if token.has_ended else time() - self.beg_loop
                    if all_lines and all_lines[-1].is_silent():
                        all_lines[-1].end = end_silence
                    else:
                        all_lines.append(SilentLine(
                            start = token.start,
                            end = end_silence
                        ))
                else:
                    current_line_tokens.append(token)
            
            # Track whether we added an in-progress line (built from current_line_tokens)
            has_in_progress_line = bool(current_line_tokens)
            if current_line_tokens:
                all_lines.append(Line().build_from_tokens(current_line_tokens))
                
        if current_silence:
            end_silence = current_silence.end if current_silence.has_ended else time() - self.beg_loop
            if all_lines and all_lines[-1].is_silent():
                all_lines[-1].end = end_silence
            else:
                all_lines.append(SilentLine(
                    start = current_silence.start,
                    end = end_silence
                ))
        if translation:
            [self.add_translation(line) for line in all_lines if not type(line) == Silence]

        # Send ONLY the new token text as an incremental update
        # Frontend will append this to the current line
        
        if not hasattr(self, '_new_token_text') or not self._new_token_text:
            return [], diarization_buffer, self.new_translation_buffer.text
        
        # Create a line containing ONLY the new token text
        # Use timing from the last token if available
        if self.new_tokens:
            new_token_line = Line()
            new_token_line.text = self._new_token_text
            new_token_line.start = self.new_tokens[0].start
            new_token_line.end = self.new_tokens[-1].end
            new_token_line.timeline_start_seconds = getattr(self.new_tokens[0], "timeline_start_seconds", None)
            new_token_line.timeline_end_seconds = getattr(self.new_tokens[-1], "timeline_end_seconds", None)
            new_token_line.speaker_id = "Speaker 1"  # Will be overridden by audio source
            
            # Mark line_complete if the next token after these new ones is silence
            # (meaning this batch of tokens completes the current line)
            new_token_line.line_complete = False
            if self.all_tokens:
                # Find where these new tokens are in all_tokens
                for i, token in enumerate(self.all_tokens):
                    if self.new_tokens and token == self.new_tokens[-1]:
                        # Check if next token is silence or we're at the end
                        if i + 1 < len(self.all_tokens) and self.all_tokens[i + 1].is_silence():
                            new_token_line.line_complete = True
                        break
            
            return [new_token_line], diarization_buffer, self.new_translation_buffer.text
        
        return [], diarization_buffer, self.new_translation_buffer.text
