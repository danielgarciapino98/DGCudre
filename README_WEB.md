# Acceso web integrado de DGCuadres/POS

La interfaz web es una función opcional del programa de escritorio y comparte su base de datos y configuración. No es necesario iniciar un segundo programa:

1. Abra DGCuadres/POS y entre en **Configuración → Acceso web desde el móvil**.
2. Active **Iniciar el servidor web junto con DGCuadres/POS** y guarde.
3. Para que otros dispositivos de la misma red puedan conectarse, configure la dirección de escucha como `0.0.0.0` y permita el puerto elegido en el firewall de Windows.
4. En el móvil abra `http://IP-DE-LA-PC:PUERTO` (puerto predeterminado: `8000`).

El servidor está desactivado por defecto y escucha en `127.0.0.1` hasta que se cambie la configuración. El acceso web no incluye inicio de sesión; actívelo únicamente en una red de confianza. La dirección `0.0.0.0` escucha en todas las interfaces de red.

`ejecutar_web.bat` se conserva como acceso directo compatible, pero ahora abre la aplicación de escritorio. La configuración, el inicio, el estado y el cierre del servidor web se administran desde DGCuadres/POS.

## IA compatible con OpenAI

La IA utiliza la API compatible con OpenAI (`/v1/models` y `/v1/chat/completions`). En **Configuración → Inteligencia Artificial** indique la URL del servidor, por ejemplo `http://127.0.0.1:8081`, el modelo si no desea detección automática y la API key si el servidor la exige. La clave se envía mediante `Authorization: Bearer ...`. Puede dejarla vacía cuando el servidor no requiera autenticación.

La aplicación se conecta a un servicio IA ya iniciado; no descarga modelos ni inicia o detiene ese servicio.

Las preguntas sobre puntos, productos, turnos, gastos y balances se responden consultando las herramientas conectadas a la base de datos; los saludos y preguntas generales no requieren una consulta de negocio. El historial del chat de escritorio se mantiene al cambiar de pantalla mientras DGCuadres sigue abierto. En la web, el historial visible se guarda en el almacenamiento local del navegador y cada navegador mantiene una conversación separada en el servidor.

En **Personal**, registre trabajadores con cargo, contacto y remuneración mensual, por turno u otra modalidad. Los descuentos salariales se registran por separado y quedan pendientes hasta su autorización; no se descuentan automáticamente de caja. Los gastos del turno se clasifican y pueden asociarse opcionalmente a un trabajador. En **Configuración**, defina el código y tipo de cambio manual; cada turno guarda la tasa vigente al abrirse, y el cierre separa efectivo, transferencias y moneda extranjera. Los productos admiten vencimiento opcional y un informe de próximos vencimientos. El historial web permite filtrar por trabajador, fecha o punto. Los puntos que ya tienen turnos no se pueden eliminar, para proteger sus registros; se pueden desactivar.
