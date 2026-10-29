"""Local signed-license validation for DGCuadres/POS."""
import base64
import calendar
import hashlib
import json
import os
import platform
import re
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from database import BusinessError

PUBLIC_KEY_B64 = "XbQ9rWBKMOTffaXNU0wrtVPzg8NhrqI08oHpH0jNKZY"


def _b64decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def add_six_months(day):
    month_index = day.month - 1 + 6
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def device_activation_id():
    if platform.system() == "Windows":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
            ) as key:
                machine_id, _ = winreg.QueryValueEx(key, "MachineGuid")
        except OSError as exc:
            raise BusinessError(
                "No se pudo obtener el identificador de esta computadora."
            ) from exc
        if not isinstance(machine_id, str) or not machine_id.strip():
            raise BusinessError(
                "No se pudo obtener el identificador de esta computadora."
            )
    else:
        machine_id = ""
        for machine_id_path in (
            Path("/etc/machine-id"),
            Path("/var/lib/dbus/machine-id"),
        ):
            try:
                machine_id = machine_id_path.read_text(encoding="ascii").strip()
            except OSError:
                continue
            if machine_id:
                break

        if not machine_id:
            app_data = os.environ.get("XDG_CONFIG_HOME")
            data_dir = Path(app_data) if app_data else Path.home() / ".config"
            identity_path = data_dir / "DGCuadresPOS" / "device_id"
            try:
                identity_path.parent.mkdir(parents=True, exist_ok=True)
                if identity_path.exists():
                    machine_id = identity_path.read_text(encoding="ascii").strip()
                else:
                    machine_id = uuid4().hex
                    identity_path.write_text(machine_id, encoding="ascii")
            except OSError as exc:
                raise BusinessError(
                    "No se pudo crear el identificador de esta computadora."
                ) from exc

    return (
        hashlib.sha256(f"DGCuadresPOS:{machine_id}".encode("utf-8"))
        .hexdigest()[:32]
        .upper()
    )


def verify_license_code(code, today=None):
    if not isinstance(code, str):
        raise BusinessError("El código de licencia no es válido.")
    code = code.strip()
    if not code or len(code) > 4096:
        raise BusinessError("El código de licencia no es válido.")
    try:
        payload_part, signature_part = code.split(".", 1)
        payload_bytes = _b64decode(payload_part)
        signature = _b64decode(signature_part)
        public_key = Ed25519PublicKey.from_public_bytes(_b64decode(PUBLIC_KEY_B64))
        public_key.verify(signature, payload_bytes)
        payload = json.loads(payload_bytes)
        if not isinstance(payload, dict) or payload.get("version") != 2:
            raise ValueError("Formato de licencia no compatible.")
        customer_value = payload["customer"]
        if not isinstance(customer_value, str):
            raise ValueError("El cliente debe ser texto.")
        customer = customer_value.strip()
        issued_on = date.fromisoformat(payload["issued_on"])
        licensed_device_id = payload["device_id"]
        if (
            not customer
            or len(customer) > 120
            or payload.get("duration_months") != 6
            or not isinstance(licensed_device_id, str)
            or not re.fullmatch(r"[0-9A-F]{32}", licensed_device_id)
        ):
            raise ValueError("Los datos de la licencia no son válidos.")
    except (InvalidSignature, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise BusinessError("El código de licencia no es válido.") from exc

    current_device_id = device_activation_id()
    if licensed_device_id != current_device_id:
        raise BusinessError(
            "Este código corresponde a otra computadora. Solicite una licencia "
            "emitida para el identificador de este equipo."
        )

    current_date = today or datetime.now(timezone.utc).date()
    if issued_on > current_date:
        raise BusinessError("La licencia todavía no está vigente.")
    return {
        "customer": customer,
        "issued_on": issued_on.isoformat(),
        "duration_months": 6,
        "device_id": licensed_device_id,
        "code": code,
    }


def validate_stored_license(license_row, today=None):
    try:
        license_data = verify_license_code(license_row["license_code"], today)
        activated_at = datetime.fromisoformat(license_row["activated_at"])
        activated_on = activated_at.date()
        expires_on = date.fromisoformat(license_row["expires_on"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BusinessError("Los datos guardados de la licencia no son válidos.") from exc
    if expires_on != add_six_months(activated_on):
        raise BusinessError("Los datos guardados de la licencia no son válidos.")
    current_date = today or datetime.now(timezone.utc).date()
    if expires_on < current_date:
        raise BusinessError("La licencia venció. Ingrese un código de renovación.")
    return {
        **license_data,
        "activated_on": activated_on.isoformat(),
        "expires_on": expires_on.isoformat(),
    }


def license_signing_key_path():
    import os
    from pathlib import Path

    app_data = os.environ.get("APPDATA")
    base = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
    return base / "DGCuadresPOS" / "license_signing_private.pem"
