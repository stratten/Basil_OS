import type { ReactNode } from 'react';
import type { ArtifactFileCategory } from './artifactFileType';

/*
 * Outline file-type icons on a 24px grid with a 1.75 stroke, drawn in the style of Lucide (https://lucide.dev, ISC license: free to use, copy, and modify). Most paths follow the Lucide originals; the config glyph is drawn to match. They are inlined to avoid a dependency and render in `currentColor`, which the stylesheet sets per category.
 */

const FILE_OUTLINE = (
  <>
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
    <path d="M14 2v4a2 2 0 0 0 2 2h4" />
  </>
);

const GLYPHS: Record<ArtifactFileCategory, ReactNode> = {
  markdown: (
    <>
      {FILE_OUTLINE}
      <path d="M10 9H8" />
      <path d="M16 13H8" />
      <path d="M16 17H8" />
    </>
  ),
  html: (
    <>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
      <path d="M2 12h20" />
    </>
  ),
  code: (
    <>
      {FILE_OUTLINE}
      <path d="m10 13-2 2 2 2" />
      <path d="m14 17 2-2-2-2" />
    </>
  ),
  shell: (
    <>
      <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />
      <path d="m7 11 2-2-2-2" />
      <path d="M11 13h4" />
    </>
  ),
  data: (
    <>
      {FILE_OUTLINE}
      <path d="M8 13h2" />
      <path d="M14 13h2" />
      <path d="M8 17h2" />
      <path d="M14 17h2" />
    </>
  ),
  config: (
    <>
      {FILE_OUTLINE}
      <circle cx="12" cy="15" r="2" />
      <path d="M12 11.5v1.5" />
      <path d="M12 17v1.5" />
      <path d="M8.5 15H10" />
      <path d="M14 15h1.5" />
    </>
  ),
  text: (
    <>
      {FILE_OUTLINE}
      <path d="M8 13h8" />
      <path d="M8 17h5" />
    </>
  ),
  pdf: (
    <>
      {FILE_OUTLINE}
      <path d="M9 18v-5h1.5a1.5 1.5 0 0 1 0 3H9" />
      <path d="M14 18v-5" />
      <path d="M14 13h2" />
    </>
  ),
  image: (
    <>
      <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
    </>
  ),
  archive: (
    <>
      <rect width="20" height="5" x="2" y="3" rx="1" />
      <path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8" />
      <path d="M10 12h4" />
    </>
  ),
  other: FILE_OUTLINE,
};

export interface FileTypeIconProps {
  category: ArtifactFileCategory;
  size?: number;
  className?: string;
}

/** A decorative icon; the row it sits in carries the accessible name and type label. */
export function FileTypeIcon({ category, size = 14, className }: FileTypeIconProps) {
  return (
    <svg
      className={['file-type-icon', `file-type-icon--${category}`, className].filter(Boolean).join(' ')}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {GLYPHS[category]}
    </svg>
  );
}
