import type { CSSProperties } from 'react';

import agentClose from './assets/native-symbols/agent-close.png';
import agentCollapse from './assets/native-symbols/agent-collapse.png';
import agentSidebar from './assets/native-symbols/agent-sidebar.png';
import analysisActionItems from './assets/native-symbols/analysis-action-items.png';
import analysisCustom from './assets/native-symbols/analysis-custom.png';
import analysisDecisions from './assets/native-symbols/analysis-decisions.png';
import analysisQuestions from './assets/native-symbols/analysis-questions.png';
import analysisSentiment from './assets/native-symbols/analysis-sentiment.png';
import analysisSuggestedActions from './assets/native-symbols/analysis-suggested-actions.png';
import analysisSummary from './assets/native-symbols/analysis-summary.png';
import conversationNew from './assets/native-symbols/conversation-new.png';
import conversationSidebar from './assets/native-symbols/conversation-sidebar.png';
import conversationSidebarExpand from './assets/native-symbols/conversation-sidebar-expand.png';
import copy from './assets/native-symbols/copy.png';
import localPreviewPlay from './assets/native-symbols/local-preview-play.png';
import localPreviewRefresh from './assets/native-symbols/local-preview-refresh.png';
import localPreviewSend from './assets/native-symbols/local-preview-send.png';
import openFile from './assets/native-symbols/open-file.png';
import openLocalWebPreview from './assets/native-symbols/open-local-web-preview.png';
import openPreviewWindow from './assets/native-symbols/open-preview-window.png';
import showInFolder from './assets/native-symbols/show-in-folder.png';

export type NativeSymbolName =
  | 'conversationNew'
  | 'conversationSidebar'
  | 'conversationSidebarExpand'
  | 'copy'
  | 'openFile'
  | 'showInFolder'
  | 'openPreviewWindow'
  | 'openLocalWebPreview'
  | 'analysisActionItems'
  | 'analysisSuggestedActions'
  | 'analysisSummary'
  | 'analysisDecisions'
  | 'analysisQuestions'
  | 'analysisSentiment'
  | 'analysisCustom'
  | 'folder'
  | 'openPreview'
  | 'close'
  | 'collapse'
  | 'sidebar'
  | 'refresh'
  | 'openExternal'
  | 'send'
  | 'play';

const symbolSources: Record<NativeSymbolName, string> = {
  conversationNew,
  conversationSidebar,
  conversationSidebarExpand,
  copy,
  openFile,
  showInFolder,
  openPreviewWindow,
  openLocalWebPreview,
  analysisActionItems,
  analysisSuggestedActions,
  analysisSummary,
  analysisDecisions,
  analysisQuestions,
  analysisSentiment,
  analysisCustom,
  folder: showInFolder,
  openPreview: openPreviewWindow,
  close: agentClose,
  collapse: agentCollapse,
  sidebar: agentSidebar,
  refresh: localPreviewRefresh,
  openExternal: openLocalWebPreview,
  send: localPreviewSend,
  play: localPreviewPlay,
};

const symbolSizes: Record<NativeSymbolName, number> = {
  conversationNew: 12,
  conversationSidebar: 12,
  conversationSidebarExpand: 20,
  copy: 13,
  openFile: 16,
  showInFolder: 16,
  openPreviewWindow: 16,
  openLocalWebPreview: 16,
  analysisActionItems: 14,
  analysisSuggestedActions: 14,
  analysisSummary: 14,
  analysisDecisions: 14,
  analysisQuestions: 14,
  analysisSentiment: 14,
  analysisCustom: 14,
  folder: 16,
  openPreview: 16,
  close: 16,
  collapse: 16,
  sidebar: 12,
  refresh: 14,
  openExternal: 14,
  send: 14,
  play: 14,
};

export default function NativeSymbolIcon({
  name,
  alt = '',
  className,
  style,
  size: sizeOverride,
}: {
  name: NativeSymbolName;
  alt?: string;
  className?: string;
  style?: CSSProperties;
  /** Overrides this icon's default size (see symbolSizes) for one usage site. */
  size?: number;
}) {
  const size = sizeOverride ?? symbolSizes[name];
  // 'play' is drawn as an outline triangle rather than a rasterized mask image:
  // every other symbol in this set is either a thin-stroke outline PNG or an
  // outline SVG elsewhere in the app, so a solid filled triangle stood out as
  // visually inconsistent. An inline stroked SVG matches that outline language
  // exactly and stays crisp at the small sizes this icon renders at.
  if (name === 'play') {
    return (
      <svg
        className={className}
        role={alt ? 'img' : undefined}
        aria-label={alt || undefined}
        aria-hidden={alt ? undefined : true}
        viewBox="0 0 24 24"
        style={{
          display: 'inline-block',
          flex: '0 0 auto',
          width: size,
          height: size,
          ...style,
        }}
      >
        <path
          d="M7 4.5 19 12 7 19.5Z"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.75}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  const source = symbolSources[name];
  return (
    <span
      className={className}
      role={alt ? 'img' : undefined}
      aria-label={alt || undefined}
      aria-hidden={alt ? undefined : true}
      style={{
        display: 'inline-block',
        flex: '0 0 auto',
        width: size,
        height: size,
        backgroundColor: 'currentColor',
        WebkitMaskImage: `url("${source}")`,
        maskImage: `url("${source}")`,
        WebkitMaskPosition: 'center',
        maskPosition: 'center',
        WebkitMaskRepeat: 'no-repeat',
        maskRepeat: 'no-repeat',
        WebkitMaskSize: 'contain',
        maskSize: 'contain',
        ...style,
      }}
    />
  );
}
