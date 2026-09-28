export function readerSessionSecret(): string {
  const value = process.env.APP_SECRET?.trim();
  if (value) return value;
  return "dev-secret-change-me";
}
