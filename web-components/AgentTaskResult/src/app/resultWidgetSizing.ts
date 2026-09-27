type LayoutNode = {
  offsetHeight?: number;
  classList?: { contains: (value: string) => boolean };
  children?: ArrayLike<LayoutNode>;
  matches?: (selector: string) => boolean;
  querySelector?: (selector: string) => LayoutNode | null;
};

type LayoutContainer = {
  children: ArrayLike<LayoutNode>;
};

function readOffsetHeight(element: LayoutNode): number | null {
  const value = element.offsetHeight;
  return typeof value === 'number' ? value : null;
}

type ScrollHeightReadable = {
  offsetHeight?: number;
  scrollHeight?: number;
};

export function measureOverlayDialogIntrinsicHeight(
  dialog: ScrollHeightReadable | null,
): number {
  if (!dialog) return 0;
  const offsetHeight = typeof dialog.offsetHeight === 'number' ? dialog.offsetHeight : 0;
  const scrollHeight = typeof dialog.scrollHeight === 'number' ? dialog.scrollHeight : 0;
  return Math.max(offsetHeight, scrollHeight, 0);
}

export function measureContentAreaLayoutHeight(
  contentArea: LayoutContainer | null,
  isAbsolutePositioned: (element: LayoutNode) => boolean = defaultIsAbsolutePositioned,
): number {
  if (!contentArea) return 144;

  let total = 0;
  for (const child of Array.from(contentArea.children)) {
    const offsetHeight = readOffsetHeight(child);
    if (offsetHeight === null) continue;
    if (isAbsolutePositioned(child)) continue;
    total += offsetHeight;
  }

  return total > 0 ? total : 144;
}

export function measureScrollRegionIntrinsicHeight(
  scrollRegion: LayoutContainer | null,
): number {
  if (!scrollRegion) return 0;

  let total = 0;
  for (const child of Array.from(scrollRegion.children)) {
    const offsetHeight = readOffsetHeight(child);
    if (offsetHeight !== null) {
      total += offsetHeight;
    }
  }
  return total;
}

function isThinkingContainer(element: LayoutNode): boolean {
  const classList = element.classList;
  return classList?.contains('thinking-segments') === true
    || classList?.contains('thinking-section') === true;
}

export function measureStableScrollRegionHeight(
  scrollRegion: {
    children: ArrayLike<LayoutNode>;
  } | null,
  measureOuterBlockSize: (element: LayoutNode) => number = defaultOuterBlockSize,
  measureBlockPadding: (element: object) => number = defaultBlockPadding,
): number {
  if (!scrollRegion) return 0;

  const stableChildrenHeight = Array.from(scrollRegion.children).reduce((total, child) => {
    if (isThinkingContainer(child)) return total;
    return total + measureOuterBlockSize(child);
  }, 0);
  return stableChildrenHeight + measureBlockPadding(scrollRegion);
}

export function measureExpandedWidgetContentHeight(input: {
  contentArea: LayoutContainer | null;
  mainContent: {
    children: ArrayLike<LayoutNode>;
    scrollHeight?: number;
  } | null;
  isAbsolutePositioned?: (element: LayoutNode) => boolean;
}): number {
  const isAbsolutePositioned = input.isAbsolutePositioned ?? defaultIsAbsolutePositioned;
  const { contentArea, mainContent } = input;
  if (!contentArea) return 144;

  let total = 0;
  for (const child of Array.from(contentArea.children)) {
    if (isAbsolutePositioned(child)) continue;

    const shell = child.matches?.('.result-content-shell')
      ? child
      : child.querySelector?.('.result-content-shell');
    if (shell?.children) {
      for (const shellChild of Array.from(shell.children)) {
        const shellChildClassList = shellChild.classList;
        if (shellChildClassList?.contains('main-content') && shellChild.children) {
          total += measureStableScrollRegionHeight({ children: shellChild.children });
          continue;
        }
        total += defaultOuterBlockSize(shellChild);
      }
      continue;
    }

    const childHeight = readOffsetHeight(child);
    if (childHeight === null) continue;
    total += childHeight;
  }

  if (total > 0) return total;
  return measureStableScrollRegionHeight(mainContent) || 144;
}

function defaultIsAbsolutePositioned(element: LayoutNode): boolean {
  if (typeof HTMLElement !== 'undefined' && element instanceof HTMLElement) {
    return getComputedStyle(element).position === 'absolute';
  }
  return false;
}

function defaultOuterBlockSize(element: LayoutNode): number {
  const height = readOffsetHeight(element) ?? 0;
  if (typeof HTMLElement === 'undefined' || !(element instanceof HTMLElement)) {
    return height;
  }
  const style = getComputedStyle(element);
  return height
    + (Number.parseFloat(style.marginTop) || 0)
    + (Number.parseFloat(style.marginBottom) || 0);
}

function defaultBlockPadding(element: object): number {
  if (typeof HTMLElement === 'undefined' || !(element instanceof HTMLElement)) {
    return 0;
  }
  const style = getComputedStyle(element);
  return (Number.parseFloat(style.paddingTop) || 0)
    + (Number.parseFloat(style.paddingBottom) || 0);
}
