import { useEffect, useMemo, useState } from 'react';
import { WindowControlButton } from '@shared/WindowControlButton';
import { MemoryFileEditor } from '../components/MemoryFileEditor';
import { MemoryProposalEditor } from '../components/MemoryProposalEditor';
import { SkillCandidateEditor } from '../components/SkillCandidateEditor';
import { SkillEditor } from '../components/SkillEditor';
import { applyPreviewTheme, closeEditor, minimizeEditor, registerInitHandler } from '../services/bridge';
import type { ProfileEditorConfig } from '../types';

interface Props {
  initialConfig: ProfileEditorConfig;
}

export function ProfileEditorApp({ initialConfig }: Props) {
  const [config, setConfig] = useState(initialConfig);

  useEffect(() => {
    applyPreviewTheme(config.theme, config.fonts);
    registerInitHandler((nextConfig) => {
      applyPreviewTheme(nextConfig.theme, nextConfig.fonts);
      setConfig(nextConfig);
    });
  }, [config.theme, config.fonts]);

  const title = useMemo(() => titleForConfig(config), [config]);

  return (
    <div className="basil-webkit-window-frame">
      <main className="profile-editor-window basil-webkit-window-surface">
      <header className="profile-editor-window-header">
        <div className="profile-editor-window-controls" aria-label="Window controls">
          <WindowControlButton kind="close" label="Close profile editor" className="profile-editor-window-control header-btn" onClick={closeEditor} />
          <WindowControlButton kind="minimize" label="Minimize profile editor" className="profile-editor-window-control header-btn" onClick={minimizeEditor} />
        </div>
        <div className="profile-editor-window-title-group">
          <div className="profile-editor-window-eyebrow">Basil Profile Editor</div>
          <h1 className="profile-editor-window-title">{title}</h1>
        </div>
      </header>
      <div className="profile-editor-window-content">{renderMode(config)}</div>
      </main>
    </div>
  );
}

function renderMode(config: ProfileEditorConfig) {
  switch (config.mode) {
    case 'memory_file':
      return <MemoryFileEditor apiBaseUrl={config.apiBaseUrl} fileName={config.identifier} />;
    case 'skill':
      return <SkillEditor apiBaseUrl={config.apiBaseUrl} slug={config.identifier} />;
    case 'memory_proposal':
      return <MemoryProposalEditor apiBaseUrl={config.apiBaseUrl} proposalId={config.identifier} />;
    case 'skill_candidate':
      return <SkillCandidateEditor apiBaseUrl={config.apiBaseUrl} candidateId={config.identifier} />;
    default:
      return <div className="editor-error">Unsupported editor mode.</div>;
  }
}

function titleForConfig(config: ProfileEditorConfig) {
  switch (config.mode) {
    case 'memory_file':
      return config.identifier;
    case 'skill':
      return `Saved skill: ${config.identifier}`;
    case 'memory_proposal':
      return 'Review memory proposal';
    case 'skill_candidate':
      return 'Review skill candidate';
    default:
      return 'Editor';
  }
}
