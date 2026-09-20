import { JSDOM } from "jsdom";

const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
  url: "http://localhost/",
  pretendToBeVisual: true,
});

const { window } = dom;

const keys = [
  "window",
  "document",
  "navigator",
  "HTMLElement",
  "HTMLButtonElement",
  "HTMLDivElement",
  "HTMLDetailsElement",
  "Node",
  "Element",
  "Text",
  "DocumentFragment",
  "Event",
  "MouseEvent",
  "KeyboardEvent",
  "CustomEvent",
  "MutationObserver",
  "SVGElement",
];

for (const key of keys) {
  Object.defineProperty(globalThis, key, {
    value: window[key],
    configurable: true,
  });
}

Object.defineProperty(globalThis, "getComputedStyle", {
  value: window.getComputedStyle.bind(window),
  configurable: true,
});

if (!window.PointerEvent) {
  class PointerEventShim extends window.MouseEvent {
    constructor(type, init) {
      super(type, init);
    }
  }
  Object.defineProperty(window, "PointerEvent", { value: PointerEventShim, configurable: true });
}
Object.defineProperty(globalThis, "PointerEvent", { value: window.PointerEvent, configurable: true });

if (typeof window.FocusEvent !== "function") {
  class FocusEventShim extends window.Event {
    constructor(type, init = {}) {
      super(type, init);
      this.relatedTarget = init.relatedTarget ?? null;
    }
  }
  Object.defineProperty(window, "FocusEvent", { value: FocusEventShim, configurable: true });
}
Object.defineProperty(globalThis, "FocusEvent", { value: window.FocusEvent, configurable: true });

if (typeof window.HTMLElement.prototype.scrollIntoView !== "function") {
  window.HTMLElement.prototype.scrollIntoView = function scrollIntoView() {};
}

Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 1280 });
Object.defineProperty(window, "innerHeight", { configurable: true, writable: true, value: 800 });

let hoverFine = true;
const mediaListeners = new Set();

window.matchMedia = (query) => {
  const media = String(query);
  const mql = {
    get matches() {
      return media.includes("hover") ? hoverFine : false;
    },
    media,
    onchange: null,
    addEventListener(type, listener) {
      if (type === "change") mediaListeners.add(listener);
    },
    removeEventListener(type, listener) {
      mediaListeners.delete(listener);
    },
    addListener(listener) {
      mediaListeners.add(listener);
    },
    removeListener(listener) {
      mediaListeners.delete(listener);
    },
    dispatchEvent() {
      return false;
    },
  };
  return mql;
};

window.scrollTo = () => {};
window.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
window.cancelAnimationFrame = (id) => clearTimeout(id);

class ResizeObserverShim {
  observe() {}
  unobserve() {}
  disconnect() {}
}
Object.defineProperty(window, "ResizeObserver", { value: ResizeObserverShim, configurable: true });
Object.defineProperty(globalThis, "ResizeObserver", { value: ResizeObserverShim, configurable: true });

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

globalThis.setEvidenceEnv = (options = {}) => {
  if (options.hoverFine !== undefined) hoverFine = options.hoverFine;
  if (options.width !== undefined) {
    Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: options.width });
  }
  const event = { matches: hoverFine };
  for (const listener of mediaListeners) listener(event);
  window.dispatchEvent(new window.Event("resize"));
};
