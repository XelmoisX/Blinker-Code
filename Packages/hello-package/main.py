"""Paquete de ejemplo para Blinker Code."""
import datetime


def insert_date(api):
    ed = api.editor()
    if ed is None:
        api.message("No hay ningún archivo abierto.", error=True)
        return
    text = datetime.date.today().isoformat()
    ed.group(lambda: ed.text_area.insert("insert", text))   # un solo paso de deshacer


def register(api):
    api.add_command("Hello: Insertar fecha", lambda: insert_date(api))
    api.add_command("Hello: Saludar", lambda: api.message("¡Hola desde hello-package!"))
    api.add_shortcut("<Control-Shift-H>", lambda: insert_date(api))


def unregister(api):
    pass
