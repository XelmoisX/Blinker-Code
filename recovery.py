import os, json


class RecoveryManager:
    """Respaldos de archivos sin guardar + sesión (pestañas abiertas)."""

    def __init__(self, folder):
        self.folder = folder
        self.session_path = os.path.join(folder, "session.json")
        self._last = None                      # última sesión escrita (evita escribir de más)
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            pass

    # escritura atómica: nunca queda un archivo a medias si se corta la luz
    def _write(self, path, text):
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return True
        except OSError:
            return False

    def _bak(self, rid):
        return os.path.join(self.folder, f"{rid}.bak")

    def write_backup(self, rid, text):
        return self._write(self._bak(rid), text)

    def read_backup(self, rid):
        try:
            with open(self._bak(rid), "r", encoding="utf-8", newline="") as f:
                return f.read()
        except OSError:
            return None

    def delete_backup(self, rid):
        try:
            os.remove(self._bak(rid))
        except OSError:
            pass

    def cleanup(self, keep_ids):
        """Borra los .bak que ya no pertenecen a ninguna pestaña."""
        try:
            for n in os.listdir(self.folder):
                if n.endswith(".bak") and n[:-4] not in keep_ids:
                    try:
                        os.remove(os.path.join(self.folder, n))
                    except OSError:
                        pass
        except OSError:
            pass

    def save_session(self, data):
        blob = json.dumps(data, indent=1, sort_keys=True)
        if blob != self._last and self._write(self.session_path, blob):
            self._last = blob

    def load_session(self):
        try:
            with open(self.session_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}