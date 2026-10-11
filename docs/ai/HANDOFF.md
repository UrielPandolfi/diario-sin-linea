# Handoff

**Fecha:** 2026-10-11

**Tarea:** Comentarios de un nivel, nombre de usuario y foto al verificar el correo.

## Hecho

El registro pide un nombre de usuario único. Quien ya tenía cuenta lo carga una vez en el perfil. Sin correo verificado o sin ese nombre no se comenta. El GET de comentarios es público. El check anónimo oculta nombre y foto y conserva el lector. La foto es una tarea Celery (`bytedance/sdxl-lightning-4step`) después de confirmar el correo; un fallo no deshace la verificación. Cuentas ya verificadas sin foto la piden al abrir la sesión.

## Validación

`pytest tests/test_comments.py tests/test_reader_auth.py tests/test_transactional_mail.py`: 18 passed. En el navegador local, la nota lista el comentario con nombre y la respuesta anónima. Una cuenta verificada sin nombre ve el pedido de cargarlo; el perfil muestra ese formulario.
