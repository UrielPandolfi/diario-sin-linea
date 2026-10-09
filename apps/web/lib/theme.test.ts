import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_THEME,
  THEME_BOOTSTRAP_SCRIPT,
  THEME_COOKIE,
  THEME_STORAGE_KEY,
  parseTheme,
  resolveTheme,
  themeCookie,
} from "./theme";

test("first visit without stored preference is dark, not the OS scheme", () => {
  assert.equal(DEFAULT_THEME, "dark");
  assert.equal(resolveTheme(undefined), "dark");
  assert.equal(resolveTheme(null), "dark");
  assert.equal(resolveTheme("system"), "dark");
  assert.equal(parseTheme("dark"), "dark");
  assert.equal(parseTheme("light"), "light");
  assert.equal(parseTheme("auto"), null);
});

test("explicit choice is persisted in cookie and storage keys", () => {
  assert.equal(THEME_COOKIE, "sl_theme");
  assert.equal(THEME_STORAGE_KEY, "sl-theme");
  assert.match(themeCookie("dark"), /^sl_theme=dark; Path=\/; Max-Age=31536000; SameSite=Lax$/);
  assert.doesNotMatch(THEME_BOOTSTRAP_SCRIPT, /prefers-color-scheme/);
  assert.match(THEME_BOOTSTRAP_SCRIPT, /localStorage\.getItem/);
});
