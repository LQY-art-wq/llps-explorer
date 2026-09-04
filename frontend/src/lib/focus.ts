import type { KeyboardEvent } from "react";

/** Keep Tab navigation inside a modal without intercepting its native Escape handling. */
export function trapDialogFocus(event: KeyboardEvent<HTMLElement>): void {
  if (event.key !== "Tab" || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
  const dialog = event.currentTarget;
  const view = dialog.ownerDocument.defaultView;
  const controls = Array.from(dialog.querySelectorAll<HTMLElement>(
    'a[href], button, input, select, textarea, summary, [tabindex], [contenteditable="true"]',
  )).filter((element) => {
    if (element.tabIndex < 0 || element.matches(":disabled") ||
      element.closest('[hidden], [inert], [aria-hidden="true"], [aria-disabled="true"]')) return false;
    const style = view?.getComputedStyle(element);
    return element.getClientRects().length > 0 && style?.visibility !== "hidden" &&
      style?.visibility !== "collapse";
  });
  const first = controls[0];
  const last = controls[controls.length - 1];
  if (!first || !last) {
    event.preventDefault();
    dialog.focus();
    return;
  }
  const active = dialog.ownerDocument.activeElement;
  const outsideTabOrder = !controls.some((element) => element === active);
  if (outsideTabOrder || (event.shiftKey ? active === first : active === last)) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
  }
}
