export type HomeVista = "principal" | "ultimas";

export function parseVista(value: string | null): HomeVista {
  return value === "ultimas" ? "ultimas" : "principal";
}
