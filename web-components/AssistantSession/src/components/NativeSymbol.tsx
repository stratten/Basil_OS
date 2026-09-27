import type { CSSProperties } from 'react';

const symbolUrls = {
  close: new URL('../../../shared/assets/native-symbols/assistant-close.png', import.meta.url).href,
  minimize: new URL('../../../shared/assets/native-symbols/assistant-minimize.png', import.meta.url).href,
  collapse: new URL('../../../shared/assets/native-symbols/assistant-collapse.png', import.meta.url).href,
  history: new URL('../../../shared/assets/native-symbols/assistant-history.png', import.meta.url).href,
  mic: new URL('../../../shared/assets/native-symbols/assistant-mic.png', import.meta.url).href,
  keyboard: new URL('../../../shared/assets/native-symbols/assistant-keyboard.png', import.meta.url).href,
  micFill: new URL('../../../shared/assets/native-symbols/assistant-mic-fill.png', import.meta.url).href,
  stop: new URL('../../../shared/assets/native-symbols/assistant-stop.png', import.meta.url).href,
  check: new URL('../../../shared/assets/native-symbols/assistant-check.png', import.meta.url).href,
  edit: new URL('../../../shared/assets/native-symbols/assistant-pencil.png', import.meta.url).href,
  cancel: new URL('../../../shared/assets/native-symbols/assistant-cancel.png', import.meta.url).href,
  save: new URL('../../../shared/assets/native-symbols/assistant-save.png', import.meta.url).href,
  refine: new URL('../../../shared/assets/native-symbols/assistant-refine.png', import.meta.url).href,
  pencil: new URL('../../../shared/assets/native-symbols/assistant-pencil.png', import.meta.url).href,
  submit: new URL('../../../shared/assets/native-symbols/assistant-submit.png', import.meta.url).href,
  copyRich: new URL('../../../shared/assets/native-symbols/assistant-copy-rich.png', import.meta.url).href,
  copyMarkdown: new URL('../../../shared/assets/native-symbols/assistant-copy-markdown.png', import.meta.url).href,
  copied: new URL('../../../shared/assets/native-symbols/assistant-copied.png', import.meta.url).href,
  sidebar: new URL('../../../shared/assets/native-symbols/assistant-sidebar.png', import.meta.url).href,
  search: new URL('../../../shared/assets/native-symbols/assistant-search.png', import.meta.url).href,
} as const;

export type NativeSymbolName = keyof typeof symbolUrls;

export function NativeSymbol({
  name,
  size,
  className,
}: {
  name: NativeSymbolName;
  size: number;
  className?: string;
}) {
  const style = {
    width: size,
    height: size,
    WebkitMaskImage: `url("${symbolUrls[name]}")`,
    maskImage: `url("${symbolUrls[name]}")`,
  } as CSSProperties;
  return <span className={className} style={style} aria-hidden="true" />;
}
