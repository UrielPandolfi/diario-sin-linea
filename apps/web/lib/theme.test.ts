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

test("first visit without stored preference is light, not OS dark", () => {
  assert.equal(DEFAULT_THEME, "light");
  assert.equal(resolveTheme(undefined), "light");
  assert.equal(resolveTheme(null), "light");
  assert.equal(resolveTheme("system"), "light");
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
