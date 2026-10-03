import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Términos y condiciones",
  description: "Condiciones de uso de Sin Línea.",
  alternates: { canonical: "/terminos" },
};

export default function TermsPage() {
  return (
    <div className="mx-auto min-h-screen max-w-measure px-4 py-8 md:px-6">
      <p className="font-sans text-[12px] uppercase tracking-[0.16em] text-accent">Condiciones</p>
      <h1 className="mt-2 font-heading text-3xl font-semibold text-primary">Términos y condiciones</h1>
      <div className="mt-6 space-y-4 font-sans text-sm leading-relaxed text-secondary">
        <p>
          Sin Línea es un medio digital. La identidad legal del responsable todavía no está publicada
          en el sitio. Hasta que lo esté, una consulta se hace por <Link href="/contacto">Contacto</Link>.
        </p>
        <h2 className="font-heading text-lg text-primary">Cuenta</h2>
        <p>
          Crear una cuenta pide un email y una contraseña de al menos 8 caracteres. Esa cuenta permite
          ver el inicio y usar localidad, Me gusta, Guardados y Perfil. No compartas la contraseña.
        </p>
        <p>
          Podés pedir el restablecimiento desde el ingreso si el correo está configurado, o cambiar la
          contraseña desde Perfil indicando la actual. También podés pedir la eliminación de la cuenta
          desde Perfil. Esa solicitud queda como un caso para revisión; no borra los datos al enviarla.
        </p>
        <h2 className="font-heading text-lg text-primary">Qué se publica</h2>
        <p>
          Una nota visible es la versión que pasó la auditoría y fue publicada. El sitio puede
          actualizar ese texto cuando hay información nueva. Las fuentes enlazan a la URL original.
          Las imágenes de portada pueden estar generadas. El contenido informa; no reemplaza una
          fuente oficial ni un asesoramiento profesional.
        </p>
        <h2 className="font-heading text-lg text-primary">Uso del sitio</h2>
        <p>
          No uses el sitio para suplantar a otra persona, interferir el servicio ni extraer datos de
          cuentas ajenas. Las consultas y los reportes deben referirse a lo que querés corregir o
          preguntar.
        </p>
        <p>
          El detalle de los datos está en la <Link href="/privacidad">Política de privacidad</Link>.
        </p>
      </div>
    </div>
  );
}
