"""Device adapters: simulation (default) and read-only MikroTik export."""
import logging

from services.demo_data import BASE_CONFIG

logger = logging.getLogger(__name__)


class AdapterError(Exception):
    pass


class SimulationAdapter:
    name = 'simulation'

    def collect_config(self, device):
        return device.lab_config or BASE_CONFIG

    def check_status(self, device):
        return 'ONLINE'


class MikrotikAdapter:
    """Read-only /export collector. Credentials come from the linked Router."""
    name = 'mikrotik'

    def collect_config(self, device):
        router = device.router
        if router is None:
            raise AdapterError('Perangkat belum ditautkan ke data Router MikroTik.')
        from security import router_credentials
        from mikrotik import MikrotikClient, MikrotikError

        password, key = router_credentials(router)
        client = MikrotikClient(
            host=router.host, port=router.port, username=router.username,
            password=password, ssh_key=key, timeout=20)
        try:
            client.connect()
            code, out, err = client._exec('/export terse', timeout=60)
            if code != 0 or not out.strip():
                raise AdapterError(f'Export gagal: {err.strip()[:200]}')
            return out
        except MikrotikError as exc:
            raise AdapterError(str(exc))
        finally:
            client.close()

    def check_status(self, device):
        router = device.router
        if router is None:
            return 'UNKNOWN'
        from security import router_credentials
        from mikrotik import MikrotikClient

        password, key = router_credentials(router)
        client = MikrotikClient(host=router.host, port=router.port,
                                username=router.username, password=password,
                                ssh_key=key, timeout=10)
        try:
            ok, _ = client.test_connection()
            return 'ONLINE' if ok else 'OFFLINE'
        finally:
            client.close()


def get_adapter(device):
    if device.adapter == 'mikrotik':
        return MikrotikAdapter()
    return SimulationAdapter()
