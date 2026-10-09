// @ts-check
"use strict";

/**
 * Look up an element and check its type, so later code needs no casts.
 * @template {HTMLElement} T
 * @param {string} id
 * @param {new () => T} type
 * @returns {T}
 */
function byId(id, type) {
  const el = document.getElementById(id);
  if (!(el instanceof type)) {
    throw new Error(`Missing element #${id}`);
  }
  return el;
}
