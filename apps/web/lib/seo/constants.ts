export const SITE_NAME = "Sin Línea";
export const SITE_DESCRIPTION =
  "Medio informativo digital centrado en sucesos, no en noticias sueltas.";
export const OG_LOCALE = "es_AR";
export const DOCUMENT_LANG = "es-AR";
export const DEFAULT_OG_IMAGE_PATH = "/og-default.png";
export const OG_IMAGE_WIDTH = 1200;
export const OG_IMAGE_HEIGHT = 630;
export const FALLBACK_SITE_URL = "http://localhost:3000";
export const SITEMAP_STATIC_PATHS = ["/", "/en-vivo", "/local", "/contacto", "/como-funciona"] as const;
export const ROBOTS_DISALLOW = [
  "/admin",
  "/entrar",
  "/onboarding",
  "/seguimiento",
  "/seguidos",
  "/notificaciones",
  "/guardados",
  "/perfil",
] as const;
