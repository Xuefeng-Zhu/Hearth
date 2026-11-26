import { createContext, h, render } from "preact";
import { useContext } from "preact/hooks";

const State = createContext(null);

export function createStore(initial) {
  let snapshot = initial;
  const listeners = new Set();
  return {
    get state() { return snapshot; },
    update(changes) {
      if (Object.keys(changes).every((key) => Object.is(changes[key], snapshot[key]))) return;
      snapshot = { ...snapshot, ...changes };
      for (const listener of listeners) listener(snapshot);
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export function useAppState() {
  return useContext(State);
}

// Commit before legacy focus and scroll code reads the updated DOM.
export function mountStore(host, store, Component, props, keys) {
  function paint(snapshot) {
    render(h(State.Provider, { value: snapshot }, h(Component, props)), host);
  }
  paint(store.state);
  let previous = store.state;
  return store.subscribe((snapshot) => {
    if (keys.every((key) => Object.is(previous[key], snapshot[key]))) return;
    previous = snapshot;
    paint(snapshot);
  });
}
