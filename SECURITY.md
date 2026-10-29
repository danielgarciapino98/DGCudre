# Aviso de seguridad y plan de implementación

## Incidente de configuración
La versión anterior del repositorio incluía un `config.ini` con una credencial de IA y datos identificativos de configuración, además de una base SQLite operativa. Considera expuesta cualquier clave que haya estado en el historial del repositorio: revócala en el proveedor y crea otra. Borrar un archivo en un commit nuevo no elimina las copias de los commits anteriores; si hace falta retirar los datos del historial, coordina una limpieza del historial y revisa forks/clones.

## Datos locales
- No subas `config.ini`, bases de datos reales, copias de seguridad ni archivos con secretos.
- Crea la configuración local a partir de `config.example.ini`.
- Antes de compartir registros, usa una base de datos ficticia y elimina teléfonos, nombres y transacciones reales.
- El acceso web debe mantenerse en `127.0.0.1` salvo que se configure expresamente una LAN de confianza y reglas de firewall.

## Base de roles (fase inicial)
`security_roles.py` añade tablas de usuarios y tokens de restablecimiento, importa la credencial existente de administrador como propietario sin almacenar contraseñas en texto claro y define permisos iniciales. Es una base para integrar en rutas y pantallas; por sí sola no activa todavía los roles en todos los endpoints web. El restablecimiento requiere entregar el token por un canal verificado; no debe exponerse en logs ni devolverse públicamente en producción.

## Siguiente integración necesaria
1. Inicializar el esquema de seguridad en la conexión de la aplicación.
2. Cambiar el inicio de sesión web a `authenticate_user` y asociar rol/punto al token de sesión.
3. Aplicar permisos en el servidor a cada endpoint y filtrar datos por punto asignado.
4. Añadir administración de usuarios, flujo de recuperación verificado y registro de auditoría.
5. Probar migración con una copia de la base de datos antes de desplegar.
