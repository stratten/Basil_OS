import type { CSSProperties } from 'react';

const symbolSources = {
  close: new URL('../../../shared/assets/native-symbols/transcription-close.png', import.meta.url).href,
  closeFill: new URL('../../../shared/assets/native-symbols/transcription-close-fill.png', import.meta.url).href,
  copied: new URL('../../../shared/assets/native-symbols/transcription-copied.png', import.meta.url).href,
  copy: new URL('../../../shared/assets/native-symbols/transcription-copy.png', import.meta.url).href,
  clear: new URL('../../../shared/assets/native-symbols/transcription-clear.png', import.meta.url).href,
  chevronDown: new URL('../../../shared/assets/native-symbols/assistant-chevron-down.png', import.meta.url).href,
  expand: new URL('../../../shared/assets/native-symbols/transcription-expand.png', import.meta.url).href,
  micFill: new URL('../../../shared/assets/native-symbols/transcription-mic-fill.png', import.meta.url).href,
  minimize: new URL('../../../shared/assets/native-symbols/transcription-minimize.png', import.meta.url).href,
  record: new URL('../../../shared/assets/native-symbols/transcription-record.png', import.meta.url).href,
  stop: new URL('../../../shared/assets/native-symbols/transcription-stop.png', import.meta.url).href,
  uploadDoc: new URL('../../../shared/assets/native-symbols/transcription-upload-doc.png', import.meta.url).href,
  uploadDrop: new URL('../../../shared/assets/native-symbols/transcription-upload-drop.png', import.meta.url).href,
  warning: new URL('../../../shared/assets/native-symbols/transcription-warning.png', import.meta.url).href,
  waveform: new URL('../../../shared/assets/native-symbols/transcription-waveform.png', import.meta.url).href,
} as const;

export type TranscriptionSymbolName = keyof typeof symbolSources;

export function TranscriptionSymbol({
  name,
  size,
}: {
  name: TranscriptionSymbolName;
  size: number;
}) {
  const style = {
    width: size,
    height: size,
    display: 'inline-block',
    backgroundColor: 'currentColor',
    WebkitMaskImage: `url("${symbolSources[name]}")`,
    maskImage: `url("${symbolSources[name]}")`,
  } as CSSProperties;
  return <span aria-hidden="true" className="transcription-symbol" style={style} />;
}
