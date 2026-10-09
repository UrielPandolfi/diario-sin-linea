# Correo transaccional

La API envía por HTTPS a Resend. El worker no manda estos correos. Sin `RESEND_API_KEY`, remitente y un origen `https` público, la API no dice que un mensaje salió.

Remitente: `Sin Línea <no-reply@sinlinea.ar>`. Reply-To: `contacto@sinlinea.ar`. Enlaces: `https://www.sinlinea.ar`.

## Resend

1. Entrá a Resend y creá una clave con permiso de envío. No la pongas en Vercel ni en el repositorio.
2. Agregá el dominio `sinlinea.ar` (el remitente es de ese dominio, no de un subdominio). Desactivá el rastreo de aperturas y de clics: los enlaces de contraseña no tienen que pasar por un redirect de Resend.
3. Abrí la pestaña Records del dominio y copiá cada registro tal como lo muestra Resend. El conjunto cambia según cuándo se creó el dominio (TXT/MX o CNAME). No inventes los valores.
4. Esperá a que el dominio figure verificado. Hasta ese momento Resend rechaza el envío y la API no confirma la entrega.

## Donweb

Los MX de `sinlinea.ar` siguen siendo los de Zoho. `contacto@sinlinea.ar` se lee ahí. No hace falta un buzón de Zoho para `no-reply@`: Resend lo usa solo para enviar, y las respuestas van a `contacto@` por el Reply-To.

En el DNS de Donweb:

- Pegá los registros de la pestaña Records de Resend, en el nombre que indique (suele ser `send` y `resend._domainkey`, no el dominio pelado).
- No borres ni reemplaces los MX de Zoho.
- Si ya hay un SPF en el dominio pelado, no lo sustituyas por el de Resend. Si el panel pide tocar ese TXT, sumá el `include` de Resend al registro que ya autoriza a Zoho.
- Un DMARC estricto (`p=quarantine` o `p=reject`) en el dominio pelado también juzga el correo de Zoho. No lo publiques hasta que el SPF del raíz autorice a los dos.

## Railway

En el servicio de la API (no en el frontend de Vercel):

```
RESEND_API_KEY=
EMAIL_FROM=no-reply@sinlinea.ar
EMAIL_REPLY_TO=contacto@sinlinea.ar
APP_BASE_URL=https://www.sinlinea.ar
```

`APP_BASE_URL` gana sobre `SITE_URL` solo en los enlaces del correo. Tiene que ser `https://www.sinlinea.ar`. `localhost`, `*.vercel.app` y `*.railway.app` no sirven: con esos orígenes la API no envía.

Al arrancar, la API corre `alembic upgrade head`. La revisión `0024_reader_email_verification` marca como confirmadas las cuentas que ya existían y crea los tokens de verificación. No hace falta correrla a mano.

## Qué hace el producto

- Registro: crea la cuenta, abre la sesión y, si Resend acepta el mensaje, manda el enlace de confirmación (24 horas, un solo uso). Si el envío falla, la cuenta sigue usable y la pantalla lo dice. Confirmar no inicia sesión.
- Recuperación: la respuesta es la misma si el email existe o no, y no afirma que el mensaje salió. El enlace vence en una hora, se usa una vez y no abre sesión. Después del cambio, las sesiones anteriores dejan de servir.
- Cambio de contraseña desde Perfil: mantiene la sesión actual, cierra las otras y avisa por correo sin incluir la contraseña. Si el aviso no sale, la pantalla no dice que salió.
- Reenvíos de confirmación y pedidos de recuperación: 3 por email y 5 por IP en una hora. Si Redis no responde, se rechazan.
