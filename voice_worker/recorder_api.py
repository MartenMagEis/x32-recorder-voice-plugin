"""Tiny HTTP client for the x32-recorder REST API - the worker's only way to read settings and to
act (it runs in its own Python environment, without Django)."""
import json
import urllib.error
import urllib.request


class ApiError(Exception):
    pass


class RecorderApi:
    def __init__(self, base_url, timeout_s=5.0):
        self.base = base_url.rstrip('/')
        self.timeout_s = timeout_s

    def _call(self, method, path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, method=method,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                text = resp.read()
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get('error', '')
            except Exception:
                detail = ''
            raise ApiError(f'{method} {path}: HTTP {e.code} {detail}'.strip()) from e
        except OSError as e:
            raise ApiError(f'{method} {path}: {e}') from e
        return json.loads(text) if text else None

    def get(self, path):
        return self._call('GET', path)

    def post(self, path, data=None):
        return self._call('POST', path, data if data is not None else {})

    def put(self, path, data):
        return self._call('PUT', path, data)

    def delete(self, path):
        return self._call('DELETE', path)

    # --- convenience -----------------------------------------------------------------------

    def plugin_config(self, plugin):
        return self.get(f'/plugins/{plugin}/config/')['values']

    def template_config(self, plugin, template_id):
        for block in self.get(f'/plugins/template-config/?template_id={template_id}')['plugins']:
            if block['plugin'] == plugin:
                return block['values']
        return None

    def active_recording(self):
        rows = self.get('/recordings/?active=1')
        return rows[0] if rows else None

    def latest_recording(self):
        rows = self.get('/recordings/?limit=1')
        return rows[0] if rows else None
