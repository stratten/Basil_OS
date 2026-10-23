import type { ReactNode } from 'react';
import type { DerivedAgentTaskArtifact } from './artifactDerivation';
import { canOpenLocalServerPreview, canOpenStaticLocalWebPreview } from './artifactPreviewEligibility';
import {
  buildLocalServerPreview,
  buildStaticLocalWebPreview,
  openContainingFolder,
  openFile,
  openFilePreviewWindow,
  openLocalWebPreview,
} from '../../services/bridge';

type PreviewAction = 'open-file' | 'show-in-folder' | 'open-preview-window' | 'open-local-web-preview' | 'open-local-web-preview-server';

interface ArtifactPreviewActionBarProps {
  artifact: DerivedAgentTaskArtifact;
  agentTaskId: string;
  rootTaskId: string;
  isCurrentFileAvailable: boolean;
  renderIcon: (action: PreviewAction) => ReactNode;
}

export function ArtifactPreviewActionBar({
  artifact,
  agentTaskId,
  rootTaskId,
  isCurrentFileAvailable,
  renderIcon,
}: ArtifactPreviewActionBarProps) {
  const path = artifact.localPath;
  if (!path) return null;
  if (!isCurrentFileAvailable) {
    return <p className="tray-artifact-preview-unavailable" role="status">The task snapshot is retained, but no current file is available for Finder or detached-preview actions.</p>;
  }

  const canOpenStaticPreview = canOpenStaticLocalWebPreview(artifact);
  const canOpenServerPreview = canOpenLocalServerPreview(artifact);
  return (
    <div className="tray-artifact-preview-actions">
      <button type="button" className="tray-artifact-preview-close" onClick={() => openFile(path)} aria-label="Open File" title="Open File">{renderIcon('open-file')}</button>
      <button type="button" className="tray-artifact-preview-close" onClick={() => openContainingFolder(path)} aria-label="Show in Folder" title="Show in Folder">{renderIcon('show-in-folder')}</button>
      <button type="button" className="tray-artifact-preview-close" onClick={() => openFilePreviewWindow(path, { agentTaskId, rootTaskId })} aria-label="Open Preview Window" title="Open Preview Window">{renderIcon('open-preview-window')}</button>
      {canOpenStaticPreview && <button type="button" className="tray-artifact-preview-close" onClick={() => openLocalWebPreview(buildStaticLocalWebPreview(path, agentTaskId, artifact.artifactId, rootTaskId))} aria-label="Preview static page" title="Preview static page">{renderIcon('open-local-web-preview')}</button>}
      {canOpenServerPreview && <button type="button" className="tray-artifact-preview-close" onClick={() => openLocalWebPreview(buildLocalServerPreview(path, agentTaskId, artifact.artifactId, rootTaskId))} aria-label="Preview with local server" title="Preview with local server">{renderIcon('open-local-web-preview-server')}</button>}
    </div>
  );
}
