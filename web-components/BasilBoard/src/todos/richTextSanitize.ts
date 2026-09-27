const ALLOWED_TAGS = new Set([
  'B', 'STRONG', 'I', 'EM', 'U', 'CODE', 'PRE',
  'UL', 'OL', 'LI', 'BR', 'DIV', 'P',
]);

function sanitizeNode(node: Node, output: Node[], document: Document): void {
  if (node.nodeType === Node.TEXT_NODE) {
    output.push(document.createTextNode(node.textContent ?? ''));
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;

  const element = node as Element;
  const children: Node[] = [];
  element.childNodes.forEach((child) => sanitizeNode(child, children, document));

  if (ALLOWED_TAGS.has(element.tagName)) {
    const clean = document.createElement(element.tagName.toLowerCase());
    children.forEach((child) => clean.appendChild(child));
    output.push(clean);
  } else {
    output.push(...children);
  }
}

/** Restrict persisted rich text to the formatting tags produced by the composer toolbar. */
export function sanitizeRichText(html: string): string {
  if (!html.trim()) return '';
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  const output: Node[] = [];
  parsed.body.childNodes.forEach((child) => sanitizeNode(child, output, parsed));

  const container = parsed.createElement('div');
  output.forEach((node) => container.appendChild(node));
  return container.innerHTML;
}

/** Extract the readable text for contexts that do not render rich text. */
export function richTextToPlainText(html: string): string {
  if (!html.trim()) return '';
  return new DOMParser().parseFromString(html, 'text/html').body.textContent?.trim() ?? '';
}
