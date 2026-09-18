export type SharePayload = {
  title?: string;
  text?: string;
  path: string;
};

export function buildSharePayload(input: { title?: string; text?: string; path: string }): SharePayload {
  const path = input.path.startsWith("/") ? input.path : `/${input.path}`;
  const title = input.title?.trim();
  const text = input.text?.trim();
  return {
    path,
    ...(title ? { title } : {}),
    ...(text ? { text } : {}),
  };
}
