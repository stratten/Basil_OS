/** The copy and check icons as markup, for code that builds HTML strings (the Markdown renderer's fenced-block and quote buttons). They must stay identical to MarkdownCopyIcon and CheckmarkIcon in CopyButtons.tsx, which every other copy button in the result area uses; copyIconMarkup.test.tsx renders both and compares them. */
export const COPY_ICON_MARKUP =
  '<svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="5" width="9" height="9" rx="1.5"></rect><path d="M11 5V3.5A1.5 1.5 0 009.5 2h-6A1.5 1.5 0 002 3.5v6A1.5 1.5 0 003.5 11H5"></path></svg>';

export const CHECK_ICON_MARKUP =
  '<svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 4.5L6.5 11 3 7.5"></path></svg>';
