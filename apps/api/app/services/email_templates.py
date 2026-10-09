"""Correos transaccionales. HTML simple y texto plano, sin recursos externos."""

from __future__ import annotations

_REPLY = "contacto@sinlinea.ar"


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_message(
    *,
    subject: str,
    preheader: str,
    title: str,
    paragraphs: list[str],
    action_label: str | None,
    action_url: str | None,
    footnote: str,
) -> tuple[str, str, str]:
    lines = [title, ""]
    lines.extend(paragraphs)
    if action_url:
        lines.extend(["", action_url])
    lines.extend(["", footnote, "", "Sin Línea", _REPLY])
    text = "\n".join(lines) + "\n"

    paragraph_html = "".join(
        f'<p style="margin:0 0 16px;font-family:Georgia,\'Times New Roman\',serif;font-size:16px;line-height:1.5;color:#f3f0e8;">{_escape(paragraph)}</p>'
        for paragraph in paragraphs
    )
    action_html = ""
    if action_label and action_url:
        safe_url = _escape(action_url)
        action_html = (
            '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 20px;">'
            "<tr><td>"
            f'<a href="{safe_url}" style="display:inline-block;padding:12px 22px;background:#28594d;color:#f7f6f2;'
            'font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1;text-decoration:none;">'
            f"{_escape(action_label)}</a>"
            "</td></tr></table>"
            f'<p style="margin:0 0 20px;font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.5;color:#a8b0aa;">'
            f'O copiá este enlace:<br><a href="{safe_url}" style="color:#7fb5a8;word-break:break-all;">{safe_url}</a></p>'
        )
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#101619;">
<div style="display:none;max-height:0;overflow:hidden;color:#101619;">{_escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#101619;">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;">
<tr><td style="padding:0 0 28px;font-family:Georgia,'Times New Roman',serif;font-size:15px;letter-spacing:0.18em;color:#f3f0e8;">
SIN LÍNEA
<div style="margin-top:8px;border-top:1px solid #7fb5a8;width:72px;line-height:0;font-size:0;">&nbsp;</div>
</td></tr>
<tr><td style="padding:28px 28px 8px;background:#171e22;">
<h1 style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:28px;line-height:1.15;font-weight:normal;color:#f7f6f2;">{_escape(title)}</h1>
{paragraph_html}
{action_html}
<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.5;color:#a8b0aa;">{_escape(footnote)}</p>
</td></tr>
<tr><td style="padding:20px 4px 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.5;color:#8d968f;">
Sin Línea<br>
<a href="mailto:{_REPLY}" style="color:#7fb5a8;text-decoration:none;">{_REPLY}</a>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
    return subject, text, html


def verification_email(link: str) -> tuple[str, str, str]:
    return render_message(
        subject="Confirmá tu email en Sin Línea",
        preheader="El enlace vence en 24 horas y se usa una sola vez.",
        title="Confirmá tu email",
        paragraphs=["Creaste una cuenta en Sin Línea. Confirmá que este email es tuyo."],
        action_label="Confirmar email",
        action_url=link,
        footnote="El enlace vence en 24 horas y se puede usar una sola vez. Si no creaste la cuenta, ignorá este mensaje.",
    )


def password_reset_email(link: str) -> tuple[str, str, str]:
    return render_message(
        subject="Elegí una contraseña nueva en Sin Línea",
        preheader="El enlace vence en una hora y se usa una sola vez.",
        title="Elegí una contraseña nueva",
        paragraphs=["Recibimos un pedido para cambiar la contraseña de tu cuenta en Sin Línea."],
        action_label="Elegir contraseña",
        action_url=link,
        footnote=(
            "El enlace vence en una hora y se puede usar una sola vez. "
            "Si no pediste este cambio, ignorá este mensaje. Abrir el enlace no inicia sesión."
        ),
    )


def password_changed_email(recover_url: str) -> tuple[str, str, str]:
    return render_message(
        subject="Cambió la contraseña de tu cuenta en Sin Línea",
        preheader="Si no fuiste vos, pedí un enlace nuevo. Este mensaje no incluye la contraseña.",
        title="Cambió tu contraseña",
        paragraphs=[
            "La contraseña de tu cuenta en Sin Línea se cambió. Este mensaje no incluye esa contraseña."
        ],
        action_label="No fui yo",
        action_url=recover_url,
        footnote="Si el cambio lo hiciste vos, no tenés que hacer nada.",
    )
