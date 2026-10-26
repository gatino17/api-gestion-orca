# Avisos de soporte en terreno

El soporte y la sugerencia se guardan primero. Solo un pedido explicito a
`POST /api/soporte/<id>/aviso-terreno` intenta enviar el aviso. Requiere sesion,
tipo terreno, estado pendiente/en_proceso, sin fecha de cierre y ambos textos.
No modifica el seguimiento de los correos de cierre.

## Plantilla y vista previa

El correo incluye una version HTML con cabecera OrcaGest, numero de caso
destacado, estado, prioridad, datos del centro y bloques separados para problema
y sugerencia. Conserva una alternativa de texto simple. Los valores ingresados
por usuarios se escapan automaticamente y no se cargan imagenes o fuentes externas.

Abrir `docs/soporte-correo-vista-previa.html` en el navegador para revisar el
diseno con datos de ejemplo, sin enviar correo. Para regenerarlo desde cualquier
carpeta, ejecutar `python scripts/previsualizar_correo_soporte.py` usando la ruta
del script en el backend. El script no inicia Flask, no carga smtp.env ni consulta
la base de datos. La plantilla real esta en
`app/templates/correo/soporte_terreno.html`; la vista previa usa el mismo renderizador.

## Configuracion del servidor

El backend carga automaticamente `smtp.env` junto a `run.py` al iniciar,
independientemente de la carpeta de ejecucion. Este archivo esta excluido de
GitHub por la regla `*.env`. Solo se leen las variables SMTP y destinatarios;
no altera la base de datos ni otras configuraciones. Las variables del entorno
del proceso y la configuracion explicita de Flask tienen prioridad.

En local, el archivo ya esta preparado: completar unicamente `SMTP_PASSWORD=`
con la contrasena de aplicacion real sin espacios, guardar y reiniciar el backend.
No pegar la clave en el chat, el frontend, la documentacion ni en `smtp.env.example`.

En el servidor, crear `smtp.env` a partir de `smtp.env.example` y completar la
credencial alli, o mantener las variables en el servicio del backend. El archivo
local con la clave no se transfiere al actualizar desde GitHub. Restringir su
lectura al usuario del servicio (por ejemplo, permisos 600 en Linux si ese usuario
es el propietario). No servirlo como archivo publico ni incluirlo en respaldos
sin proteccion.

### Gmail como emisor

La cuenta emisora confirmada es agatino@orcatecnologia.cl, con acceso desde
Gmail. Los destinatarios son el grupo soporte@orcatecnologia.cl y, de forma
directa, agatino@orcatecnologia.cl. Esta copia no depende de la distribucion
del grupo al propio emisor. Ambos aparecen en el campo Para del mismo aviso.
Para esta integracion SMTP, habilitar verificacion en dos
pasos y crear una contrasena de aplicacion para OrcaGest, si Google permite esa
opcion en la cuenta. No usar la contrasena habitual ni desactivar protecciones.
Si la cuenta no permite contrasenas de aplicacion, se requiere implementar OAuth.

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USE_SSL=false
SMTP_USERNAME=agatino@orcatecnologia.cl
SMTP_FROM=agatino@orcatecnologia.cl
SMTP_PASSWORD=CONTRASENA_DE_APLICACION_DE_GOOGLE
SOPORTE_TERRENO_DESTINATARIOS=soporte@orcatecnologia.cl,agatino@orcatecnologia.cl
```

Con la sesion de agatino@orcatecnologia.cl, abrir
https://myaccount.google.com/apppasswords y, si la cuenta ofrece esa opcion,
crear una contrasena de aplicacion llamada OrcaGest. Configurar su valor como
SMTP_PASSWORD exclusivamente en el entorno del backend y reiniciarlo.
Este ejemplo documenta la configuracion; no activa el envio por si solo.

Usar una cuenta autorizada para la operacion y configurar la credencial solo en
el servidor, sin espacios de agrupacion. No compartirla por chat ni subirla al
repositorio. Por defecto usar el mismo correo autenticado como SMTP_FROM;
cualquier alias distinto debe estar autorizado en Gmail.

Google recomienda OAuth para integraciones nuevas. Este primer transporte usa
SMTP con contrasena de aplicacion y no incluye conexion OAuth.

Fuentes oficiales:
- https://support.google.com/accounts/answer/185833?hl=es
- https://developers.google.com/workspace/gmail/imap/imap-smtp

### Otros servidores

Configurar estas variables en el proceso del backend y reiniciarlo. No guardar
credenciales en GitHub ni en el frontend:

```dotenv
SMTP_HOST=smtp.proveedor.example
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USE_SSL=false
SMTP_USERNAME=cuenta-autorizada@example.com
SMTP_PASSWORD=CONFIGURAR_EN_EL_SERVIDOR
SMTP_FROM=cuenta-autorizada@example.com
SOPORTE_TERRENO_DESTINATARIOS=soporte@orcatecnologia.cl
```

Usar los datos reales y el metodo de autenticacion SMTP habilitado por el proveedor.
Este transporte utiliza usuario/contrasena con TLS; no implementa OAuth.
Para SSL implicito, usar puerto 465, SMTP_USE_SSL=true y SMTP_USE_TLS=false.
El destinatario predeterminado es soporte@orcatecnologia.cl. Se permiten varios
separados por comas. SMTP_FROM debe estar autorizado por el servidor de correo.

Al reiniciar, `ensure_soporte_schema` agrega la columna nullable `sugerencia`
y la tabla de auditoria de avisos sin modificar registros historicos. Ejecuta
su propia transaccion e impide iniciar con una migracion incompleta.

## Reintentos y confirmacion

- La aceptacion por SMTP no garantiza entrega final al buzon; revisar rebotes.
- La huella del contenido/destinatarios y una toma atomica evitan enviar dos
  veces el mismo aviso por doble clic o peticiones concurrentes.
- Editar no envia correo. Notificar explicitamente contenido cambiado crea
  una nueva instantanea y conserva el historial anterior.
- Un rechazo explicito o fallo antes de transmitir permite reintentar solo
  el correo, sin crear otro soporte.
- Un corte durante la transmision, envio parcial o fallo de base posterior
  al envio requiere comprobar el buzon antes de cualquier reenvio manual.
  No se reintenta automaticamente para evitar duplicados.
- Las pruebas utilizan SQLite y un servidor SMTP simulado; no envian correos reales.
