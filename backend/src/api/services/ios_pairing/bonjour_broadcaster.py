from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Optional


@dataclass
class BonjourBroadcastHandle:
    zeroconf: object
    service_info: object


class BonjourBroadcaster:
    """Optional Bonjour advertiser for paired iOS discovery."""

    def __init__(self, logger):
        self.logger = logger
        self._handle: Optional[BonjourBroadcastHandle] = None

    def start(self, port: int, service_name: str = "Basil Desktop") -> None:
        if self._handle is not None:
            return

        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            self.logger.warning("Bonjour broadcast requested, but python-zeroconf is not installed")
            return

        host_name = socket.gethostname()
        local_ip = self._resolve_local_ip()
        service_type = "_basil._tcp.local."
        instance_name = f"{service_name}.{service_type}"
        properties = {
            b"app": b"basil",
            b"pairing": b"enabled",
        }

        zeroconf = Zeroconf()
        service_info = ServiceInfo(
            service_type,
            instance_name,
            addresses=[socket.inet_aton(local_ip)],
            port=port,
            properties=properties,
            server=f"{host_name}.local.",
        )
        zeroconf.register_service(service_info)
        self._handle = BonjourBroadcastHandle(zeroconf=zeroconf, service_info=service_info)
        self.logger.info("Bonjour broadcast registered for Basil iOS discovery on %s:%s", local_ip, port)

    def stop(self) -> None:
        if self._handle is None:
            return
        handle = self._handle
        self._handle = None
        try:
            handle.zeroconf.unregister_service(handle.service_info)
        finally:
            handle.zeroconf.close()
        self.logger.info("Bonjour broadcast stopped")

    def _resolve_local_ip(self) -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            try:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
            except OSError:
                return "127.0.0.1"

