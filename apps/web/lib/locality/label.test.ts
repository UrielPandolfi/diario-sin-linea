import assert from "node:assert/strict";
import test from "node:test";

import { localityLabel } from "./label";

test("locality label shows province and department only for homonyms", () => {
  assert.equal(
    localityLabel({
      name: "Rosario",
      province_name: "Santa Fe",
      department_name: "Rosario",
      show_department: false,
    }),
    "Rosario, Santa Fe",
  );
  assert.equal(
    localityLabel({
      name: "San Justo",
      province_name: "Buenos Aires",
      department_name: "La Matanza",
      show_department: true,
    }),
    "San Justo, La Matanza, Buenos Aires",
  );
});
