import type { AgentTaskArtifactPresentation } from '../../artifacts/artifactContract';

export type ArtifactFileCategory =
  | 'markdown'
  | 'html'
  | 'code'
  | 'shell'
  | 'data'
  | 'config'
  | 'text'
  | 'pdf'
  | 'image'
  | 'archive'
  | 'other';

export interface ArtifactFileType {
  category: ArtifactFileCategory;
  /** Human label, used for tooltips and accessible text. */
  label: string;
  /** Stable order used when sorting by type. */
  sortRank: number;
}

const CATEGORY_INFO: Record<ArtifactFileCategory, { label: string; sortRank: number }> = {
  markdown: { label: 'Markdown', sortRank: 0 },
  html: { label: 'HTML', sortRank: 1 },
  code: { label: 'Code', sortRank: 2 },
  shell: { label: 'Script', sortRank: 3 },
  data: { label: 'Data', sortRank: 4 },
  config: { label: 'Config', sortRank: 5 },
  text: { label: 'Text', sortRank: 6 },
  pdf: { label: 'PDF', sortRank: 7 },
  image: { label: 'Image', sortRank: 8 },
  archive: { label: 'Archive', sortRank: 9 },
  other: { label: 'File', sortRank: 10 },
};

const EXTENSION_CATEGORIES: Record<string, ArtifactFileCategory> = {
  md: 'markdown',
  markdown: 'markdown',
  mdx: 'markdown',
  html: 'html',
  htm: 'html',
  sh: 'shell',
  zsh: 'shell',
  bash: 'shell',
  command: 'shell',
  applescript: 'shell',
  scpt: 'shell',
  csv: 'data',
  tsv: 'data',
  json: 'data',
  jsonl: 'data',
  xlsx: 'data',
  xls: 'data',
  plist: 'config',
  yaml: 'config',
  yml: 'config',
  toml: 'config',
  ini: 'config',
  cfg: 'config',
  conf: 'config',
  env: 'config',
  xml: 'config',
  txt: 'text',
  log: 'text',
  rtf: 'text',
  pdf: 'pdf',
  png: 'image',
  jpg: 'image',
  jpeg: 'image',
  gif: 'image',
  webp: 'image',
  svg: 'image',
  heic: 'image',
  zip: 'archive',
  tar: 'archive',
  gz: 'archive',
  tgz: 'archive',
  py: 'code',
  js: 'code',
  jsx: 'code',
  ts: 'code',
  tsx: 'code',
  swift: 'code',
  rb: 'code',
  go: 'code',
  rs: 'code',
  java: 'code',
  kt: 'code',
  c: 'code',
  h: 'code',
  cpp: 'code',
  cs: 'code',
  php: 'code',
  css: 'code',
  sql: 'code',
};

const KIND_CATEGORIES: Record<string, ArtifactFileCategory> = {
  markdown: 'markdown',
  html: 'html',
  code: 'code',
  text: 'text',
  json: 'data',
  yaml: 'config',
  xml: 'config',
  pdf: 'pdf',
};

function build(category: ArtifactFileCategory): ArtifactFileType {
  return { category, ...CATEGORY_INFO[category] };
}

function extensionOf(name: string | undefined): string | undefined {
  if (!name) return undefined;
  const base = name.split('/').pop() ?? name;
  const dot = base.lastIndexOf('.');
  if (dot <= 0 || dot === base.length - 1) return undefined;
  return base.slice(dot + 1).toLowerCase();
}

/**
 * Classifies an artifact for the document list's icon, color, and type sort. The file extension decides first, because it can say more than the review kind (a shell script and a Python file are both "code" to the review kind). The review or preview kind is the fallback for names without a known extension.
 */
export function classifyArtifactFileType(
  artifact: Pick<AgentTaskArtifactPresentation, 'displayName' | 'localPath' | 'review' | 'preview'>,
): ArtifactFileType {
  const extension = extensionOf(artifact.displayName) ?? extensionOf(artifact.localPath);
  const byExtension = extension ? EXTENSION_CATEGORIES[extension] : undefined;
  if (byExtension) return build(byExtension);

  const kind = artifact.review?.kind ?? artifact.preview?.kind;
  const byKind = kind ? KIND_CATEGORIES[kind] : undefined;
  if (byKind) return build(byKind);

  return build('other');
}
