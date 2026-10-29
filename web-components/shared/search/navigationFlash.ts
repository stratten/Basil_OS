/** Briefly rings an element a jump just scrolled to (the `data-navigation-flash` rule in `navigation-flash.css`). */
export function flashNavigationTarget(element: HTMLElement): void {
  element.removeAttribute('data-navigation-flash');
  // Reading layout restarts the animation when the same element is navigated to twice in a row.
  void element.offsetWidth;
  element.setAttribute('data-navigation-flash', '');
  const handleAnimationEnd = (event: AnimationEvent) => {
    if (event.target !== element) return;
    element.removeAttribute('data-navigation-flash');
    element.removeEventListener('animationend', handleAnimationEnd);
  };
  element.addEventListener('animationend', handleAnimationEnd);
}
