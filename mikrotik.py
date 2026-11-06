"""
MikroTik SSH/SFTP client — connects via SSH (port 22 by default),
creates backups on the router, then downloads them via SFTP.

Full backup    →  /system backup save name=<name>   (.backup file)
Config-only    →  /export file=<name>               (.rsc file)
"""
import os

import paramiko
import time
import logging
from datetime import datetime, timezone
from enum import Enum
from io import BytesIO

logger = logging.getLogger(__name__)


class BackupType(Enum):
    FULL = 'full'
    CONFIG = 'config'


class MikrotikError(Exception):
    pass


class MikrotikClient:
    def __init__(self, host, port, username, password=None,
                 ssh_key=None, timeout=15):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.ssh_key = ssh_key
        self.timeout = timeout
        self._client: paramiko.SSHClient | None = None
        self._sftp = None

    # ── connection ───────────────────────────────────────────────
    def _load_host_keys(self):
        """Load system and optional project known_hosts; reject unknown keys."""
        self._client.load_system_host_keys()
        known_hosts = os.environ.get('SSH_KNOWN_HOSTS_FILE', '').strip()
        if known_hosts:
            if not os.path.exists(known_hosts):
                raise MikrotikError(
                    f'File known_hosts tidak ditemukan: {known_hosts}. '
                    'Tambahkan host key perangkat sebelum menghubungkan.')
            self._client.load_host_keys(known_hosts)

    def connect(self):
        try:
            self._client = paramiko.SSHClient()
            self._load_host_keys()
            self._client.set_missing_host_key_policy(paramiko.RejectPolicy())
            kwargs = dict(
                hostname=self.host, port=self.port, username=self.username,
                timeout=self.timeout, banner_timeout=self.timeout,
                auth_timeout=self.timeout, look_for_keys=False,
                allow_agent=False,
            )
            if self.ssh_key:
                pkey = self._load_key(self.ssh_key)
                kwargs['pkey'] = pkey
            else:
                kwargs['password'] = self.password
            self._client.connect(**kwargs)
        except MikrotikError:
            raise
        except paramiko.BadHostKeyException as exc:
            raise MikrotikError(
                f'Host key perangkat berubah/tidak cocok ({exc.hostname}). '
                'Koneksi ditolak. Verifikasi sidik jari host sebelum memperbarui known_hosts.')
        except paramiko.AuthenticationException:
            raise MikrotikError('Authentication failed — check credentials.')
        except paramiko.SSHException as exc:
            message = str(exc)
            if 'not found in known_hosts' in message.lower() or 'host key' in message.lower():
                raise MikrotikError(
                    f'Host key {self.host}:{self.port} belum dikenal. Koneksi ditolak. '
                    'Tambahkan sidik jari yang terverifikasi ke known_hosts, misalnya: '
                    f'ssh-keyscan -p {self.port} {self.host} >> ~/.ssh/known_hosts')
            raise MikrotikError(f'SSH negotiation error: {message}')
        except Exception as exc:
            raise MikrotikError(f'Connection error: {exc}')

    @staticmethod
    def _load_key(key_data: str) -> paramiko.PKey:
        """Try RSA → Ed25519 → ECDSA in order."""
        for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                return cls.from_private_key(BytesIO(
                    key_data.encode() if isinstance(key_data, str) else key_data
                ))
            except paramiko.SSHException:
                continue
        raise MikrotikError('Unsupported SSH key format.')

    def _exec(self, command: str, timeout=60):
        if not self._client:
            self.connect()
        try:
            _stdin, stdout, _stderr = self._client.exec_command(
                command, timeout=timeout
            )
            channel = stdout.channel
            channel.settimeout(1.0)
            deadline = time.monotonic() + timeout
            out_chunks = []
            err_chunks = []

            # Drain both streams before waiting for exit status. This avoids the
            # classic Paramiko deadlock when stderr/output exceeds the pipe buffer.
            while True:
                while channel.recv_ready():
                    out_chunks.append(channel.recv(65536))
                while channel.recv_stderr_ready():
                    err_chunks.append(channel.recv_stderr(65536))
                if (channel.exit_status_ready()
                        and not channel.recv_ready()
                        and not channel.recv_stderr_ready()):
                    break
                if time.monotonic() > deadline:
                    channel.close()
                    raise MikrotikError(
                        f'Command timed out after {timeout}s: {command.split()[0]}')
                time.sleep(0.05)

            exit_code = channel.recv_exit_status()
            while channel.recv_ready():
                out_chunks.append(channel.recv(65536))
            while channel.recv_stderr_ready():
                err_chunks.append(channel.recv_stderr(65536))
            out = b''.join(out_chunks).decode('utf-8', errors='replace')
            err = b''.join(err_chunks).decode('utf-8', errors='replace')
            return exit_code, out, err
        except MikrotikError:
            raise
        except Exception as exc:
            raise MikrotikError(f'Command failed: {exc}')

    # ── public API ───────────────────────────────────────────────
    def test_connection(self):
        """Connect and fetch /system resource info."""
        try:
            self.connect()
            code, out, _ = self._exec(
                '/system resource print without-paging', timeout=15
            )
            info = {}
            for line in out.splitlines():
                if ':' in line:
                    k, v = line.split(':', 1)
                    k = k.strip().replace(' ', '_').lower()
                    info[k] = v.strip()
            return True, info
        except MikrotikError as exc:
            return False, str(exc)
        finally:
            self.close()

    def create_backup(self, backup_type: BackupType, name_prefix='backup') -> str:
        ts = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        safe = f'{name_prefix}-{ts}'
        if backup_type == BackupType.FULL:
            filename = f'{safe}.backup'
            cmd = f'/system backup save name="{safe}"'
        else:
            filename = f'{safe}.rsc'
            cmd = f'/export file="{safe}"'
        code, out, err = self._exec(cmd, timeout=90)
        for _ in range(15):
            if self._file_exists(filename):
                return filename
            time.sleep(1)
        raise MikrotikError(
            f'Backup file "{filename}" was not created on router '
            f'(exit={code}, stderr={err.strip()[:200]})'
        )

    def _file_exists(self, filename: str) -> bool:
        try:
            sftp = self._client.open_sftp()
            try:
                sftp.stat(filename)
                return True
            except IOError:
                return False
            finally:
                sftp.close()
        except Exception:
            return False

    def download_file(self, remote_name: str, local_path: str):
        if not self._client:
            self.connect()
        try:
            self._sftp = self._client.open_sftp()
            self._sftp.get(remote_name, local_path)
        except Exception as exc:
            raise MikrotikError(f'SFTP download failed: {exc}')
        finally:
            if self._sftp:
                self._sftp.close()
                self._sftp = None

    def delete_file(self, filename: str) -> bool:
        try:
            code, _, _ = self._exec(f'/file remove "{filename}"', timeout=15)
            return code == 0
        except Exception:
            return False

    def close(self):
        if self._sftp:
            try: self._sftp.close()
            except Exception: pass
            self._sftp = None
        if self._client:
            try: self._client.close()
            except Exception: pass
            self._client = None