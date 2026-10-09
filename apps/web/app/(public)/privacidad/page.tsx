import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacidad",
  description: "Qué datos guarda Sin Línea y para qué los usa.",
  alternates: { canonical: "/privacidad" },
};

export default function PrivacyPage() {
  return (
    <div className="mx-auto min-h-screen max-w-measure px-4 py-8 md:px-6">
      <p className="font-sans text-[12px] uppercase tracking-[0.16em] text-accent">Privacidad</p>
      <h1 className="mt-2 font-heading text-3xl font-semibold text-primary">Política de privacidad</h1>
      <div className="mt-6 space-y-4 font-sans text-sm leading-relaxed text-secondary">
        <p>
          Esta página describe el funcionamiento actual del sitio. La identidad legal del responsable
          (razón social, domicilio y contacto formal) todavía no está publicada. Para una consulta
          usá <Link href="/contacto">Contacto</Link>.
        </p>
        <h2 className="font-heading text-lg text-primary">Cuenta</h2>
        <p>
          Si creás una cuenta, guardamos el email y una contraseña cifrada. No guardamos la contraseña
          en texto plano. La localidad es opcional y la elegís vos; la usamos para ordenar noticias
          cercanas.
        </p>
        <h2 className="font-heading text-lg text-primary">Actividad en la cuenta</h2>
        <p>
          Con la sesión iniciada podemos registrar qué notas leíste, cuáles marcaste con Me gusta y
          cuáles guardaste. Esas señales, junto con la localidad, personalizan el orden del inicio
          para esa cuenta. Me gusta no arma una lista pública. Guardados es una lista privada de tu
          cuenta. No hay seguimiento de personas ni notificaciones.
        </p>
        <p>
          Una nota ya publicada se puede abrir con su enlace sin iniciar sesión. El inicio, En vivo,
          Local, Buscar, Guardados y Perfil piden una cuenta.
        </p>
        <h2 className="font-heading text-lg text-primary">Cookies</h2>
        <p>
          Usamos cookies propias e indispensables: <code>sl_reader</code> mantiene la sesión,{" "}
          <code>sl_admin</code> la sesión del panel interno y <code>sl_theme</code> recuerda el tema
          claro u oscuro. No hay herramientas de analítica ni publicidad de terceros, así que no hay
          un aviso para aceptar o rechazar rastreo.
        </p>
        <h2 className="font-heading text-lg text-primary">Otros tratamientos</h2>
        <p>
          Las consultas y los reportes de una nota se guardan como un caso, con el mensaje que
          escribiste y, si lo indicaste, un email. El seguimiento es un enlace privado; el sitio no
          envía un correo automático por ese caso.
        </p>
        <p>
          Si el correo transaccional está configurado, al crear la cuenta y al pedir un restablecimiento
          enviamos un enlace a ese email. Guardamos el hash del enlace, no el enlace en claro. El de
          confirmación vence a las 24 horas y el de restablecimiento a la hora. Cada uno sirve una sola
          vez. Cambiar la contraseña puede avisar por correo, sin incluirla. Si el envío no sale, no
          decimos que el mensaje fue entregado.
        </p>
        <p>
          La redacción usa procesamiento automático y modelos de lenguaje para detectar, contrastar y
          redactar. Eso no crea un perfil publicitario de quien lee.
        </p>
        <h2 className="font-heading text-lg text-primary">Eliminación</h2>
        <p>
          Desde Perfil, con la sesión iniciada, podés pedir que eliminemos la cuenta y los datos
          asociados. Eso abre un caso con el email de la sesión para poder verificar que la solicitud
          es tuya. No se borra en el momento y no hay un plazo automático publicado, porque el sitio
          todavía no ejecuta esa baja solo.
        </p>
        <p>
          También aplican los <Link href="/terminos">Términos y condiciones</Link>.
        </p>
      </div>
    </div>
  );
}
