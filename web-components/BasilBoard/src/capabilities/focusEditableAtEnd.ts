export function focusEditableAtEnd(element: HTMLElement | null | undefined): void {
  if (!element) return;
  element.focus();
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.selectNodeContents(element);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}
