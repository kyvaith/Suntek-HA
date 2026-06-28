"""Live P2P video helpers for Suntek LTE cameras."""

from __future__ import annotations

from collections.abc import Iterator
import logging
import socket
import threading
import time

from .p2p import (
    APP_COMMAND_CHANNEL,
    APP_VIDEO_COMMAND_ID,
    PACKET_ALIVE_ACK,
    PACKET_DATA,
    PACKET_HELLO_ACK,
    PACKET_LIST_RESPONSE,
    PACKET_P2P_READY,
    PACKET_P2P_REQUEST_ACK,
    PACKET_PUNCH,
    PACKET_PUNCH_TO,
    PACKET_RELAY_HELLO_ACK,
    PACKET_RELAY_PORT_ACK,
    PACKET_RELAY_READY,
    PACKET_RELAY_TO,
    P2P_REQUEST_ACCEPTED,
    build_alive_packet,
    build_app_command_frame,
    build_data_ack_packet,
    build_data_packet,
    build_hello_packet,
    build_list_request_packet,
    build_login_command,
    build_open_video_command,
    build_p2p_ready_packet,
    build_p2p_request_packet,
    build_punch_packet,
    build_relay_hello_packet,
    build_relay_packet,
    build_relay_port_packet,
    build_relay_request_packet,
    parse_control_packet,
    parse_app_command_frame,
    parse_data_packet,
    parse_list_response,
    parse_p2p_request_ack,
    parse_relay_port_ack,
    parse_relay_to,
    parse_sockaddr,
    p2p_decrypt,
    p2p_encrypt,
    profiles_for_device_api,
)

_LOGGER = logging.getLogger(__name__)

_RECV_SIZE = 0x5A0
_PUNCH_PORT_SPAN = 5


class SuntekP2PLiveError(Exception):
    """Raised when a live P2P stream cannot be opened."""


class SuntekP2PLiveStopped(Exception):
    """Raised when the HTTP client intentionally closes the live stream."""


class SuntekP2PLiveClient:
    """Blocking P2P live client.

    Home Assistant calls this from a worker thread. The protocol can legitimately
    take minutes while the LTE camera wakes up and punches through NAT.
    """

    def __init__(
        self,
        did: str,
        device_api: str | None,
        password_hash: str,
        *,
        connect_timeout: float = 360.0,
        stream_timeout: float = 240.0,
    ) -> None:
        self.did = did
        self.password_hash = password_hash
        self.profile = profiles_for_device_api(
            device_api, include_fallback=False
        )[0]
        self.connect_timeout = connect_timeout
        self.stream_timeout = stream_timeout
        self._socket: socket.socket | None = None
        self._peer: tuple[str, int] | None = None

    def close(self) -> None:
        """Close the underlying UDP socket."""
        sock = self._socket
        self._socket = None
        if sock is not None:
            sock.close()

    def iter_jpeg_frames(
        self, stop_event: threading.Event | None = None
    ) -> Iterator[bytes]:
        """Open live view and yield JPEG frames found in the P2P data stream."""
        stop_event = stop_event or threading.Event()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            self._socket = sock
            sock.bind(("0.0.0.0", 0))
            sock.settimeout(0.2)
            peer = self._connect(sock, stop_event)
            self._peer = peer
            _LOGGER.info("Suntek P2P live session ready via %s", peer)
            yield from self._iter_jpeg_frames(sock, peer, stop_event)

    def _send(self, sock: socket.socket, packet: bytes, address: tuple[str, int]) -> None:
        try:
            sock.sendto(p2p_encrypt(self.profile.key, packet), address)
        except OSError as err:
            if self._socket is None:
                raise SuntekP2PLiveStopped from err
            raise

    def _connect(
        self, sock: socket.socket, stop_event: threading.Event
    ) -> tuple[str, int]:
        """Connect to the camera using direct UDP, with relay negotiation as help."""
        _local_host, local_port = sock.getsockname()
        hello = build_hello_packet()
        p2p_request = build_p2p_request_packet(self.did, local_port=local_port)
        list_request = build_list_request_packet(self.did)
        punch = build_punch_packet(self.did)
        ready = build_p2p_ready_packet(self.did)

        hello_servers: set[tuple[str, int]] = set()
        peer_candidates: set[tuple[str, int]] = set()
        relay_candidates: set[tuple[str, int]] = set()
        next_periodic = 0.0
        next_relay_hello = 0.0
        deadline = time.monotonic() + self.connect_timeout

        for server in self.profile.servers:
            self._send(sock, hello, server)

        while time.monotonic() < deadline and not stop_event.is_set():
            now = time.monotonic()
            if hello_servers and now >= next_periodic:
                for server in hello_servers:
                    self._send(sock, p2p_request, server)
                    self._send(sock, list_request, server)
                for peer in tuple(peer_candidates):
                    self._send(sock, punch, peer)
                    self._send(sock, ready, peer)
                next_periodic = now + 1.0

            if relay_candidates and now >= next_relay_hello:
                relay_hello = build_relay_hello_packet()
                for relay in tuple(relay_candidates):
                    self._send(sock, relay_hello, relay)
                next_relay_hello = now + 2.0

            try:
                encrypted, address = sock.recvfrom(_RECV_SIZE)
            except TimeoutError:
                continue
            except OSError as err:
                if stop_event.is_set() or self._socket is None:
                    raise SuntekP2PLiveStopped from err
                raise SuntekP2PLiveError(f"P2P socket closed: {err}") from err

            try:
                packet = parse_control_packet(
                    p2p_decrypt(self.profile.key, encrypted)
                )
            except Exception:  # noqa: BLE001
                continue

            if packet.packet_type == PACKET_P2P_REQUEST_ACK:
                ack = parse_p2p_request_ack(address, packet.payload)
                _LOGGER.debug(
                    "Suntek P2P request ack from %s: %s",
                    address,
                    ack.status_text,
                )
                if ack.status == P2P_REQUEST_ACCEPTED:
                    continue

            if packet.packet_type == PACKET_HELLO_ACK:
                hello_servers.add(address)
                next_periodic = 0.0
                continue

            if packet.packet_type == PACKET_PUNCH_TO:
                peer = parse_sockaddr(packet.payload)
                self._add_peer_candidates(peer_candidates, peer)
                for candidate in tuple(peer_candidates):
                    self._send(sock, punch, candidate)
                    self._send(sock, ready, candidate)
                for host, port in self.profile.servers:
                    for server_port in (port, port + 1, port + 2):
                        self._send(sock, p2p_request, (host, server_port))
                continue

            if packet.packet_type == PACKET_PUNCH:
                for _ in range(4):
                    self._send(sock, ready, address)
                    time.sleep(0.01)
                return address

            if packet.packet_type == PACKET_P2P_READY:
                return address

            if packet.packet_type == PACKET_LIST_RESPONSE:
                for relay in parse_list_response(packet.payload):
                    relay_candidates.add(relay)
                    self._send(sock, build_relay_hello_packet(), relay)
                continue

            if packet.packet_type == PACKET_RELAY_HELLO_ACK:
                relay_candidates.add(address)
                self._send(sock, build_relay_port_packet(), address)
                continue

            if packet.packet_type == PACKET_RELAY_PORT_ACK:
                ack = parse_relay_port_ack(address, packet.payload)
                relay_request = build_relay_request_packet(
                    self.did, address, ack.relay_number
                )
                for server in self.profile.servers:
                    self._send(sock, relay_request, server)
                self._send(sock, relay_request, address)
                continue

            if packet.packet_type == PACKET_RELAY_TO:
                relay_to = parse_relay_to(address, packet.payload)
                relay_packet = build_relay_packet(self.did, relay_to.relay_number)
                for _ in range(4):
                    self._send(sock, relay_packet, relay_to.relay_address)
                self._send(sock, relay_packet, address)
                continue

            if packet.packet_type == PACKET_RELAY_READY:
                return address

        if stop_event.is_set():
            raise SuntekP2PLiveStopped

        raise SuntekP2PLiveError(
            "Timed out waiting for Suntek P2P live session "
            f"(hello={len(hello_servers)}, peers={len(peer_candidates)}, "
            f"relays={len(relay_candidates)})"
        )

    def _iter_jpeg_frames(
        self,
        sock: socket.socket,
        peer: tuple[str, int],
        stop_event: threading.Event,
    ) -> Iterator[bytes]:
        sequence = 0
        jpg_buffer = bytearray()
        next_alive = 0.0
        deadline = time.monotonic() + self.stream_timeout
        logged_non_jpeg = False

        for command in (
            build_login_command(self.password_hash),
            build_open_video_command(self.password_hash),
        ):
            self._send(
                sock,
                build_data_packet(
                    APP_COMMAND_CHANNEL,
                    sequence,
                    build_app_command_frame(APP_VIDEO_COMMAND_ID, command),
                ),
                peer,
            )
            sequence = (sequence + 1) & 0xFFFF

        while time.monotonic() < deadline and not stop_event.is_set():
            now = time.monotonic()
            if now >= next_alive:
                self._send(sock, build_alive_packet(), peer)
                next_alive = now + 5.0

            try:
                encrypted, address = sock.recvfrom(_RECV_SIZE)
            except TimeoutError:
                continue
            except OSError:
                break

            try:
                packet = parse_control_packet(
                    p2p_decrypt(self.profile.key, encrypted)
                )
            except Exception:  # noqa: BLE001
                continue

            if packet.packet_type == PACKET_ALIVE_ACK:
                continue

            if packet.packet_type != PACKET_DATA:
                continue

            try:
                data_packet = parse_data_packet(packet.payload)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Invalid Suntek P2P data packet: %s", err)
                continue

            self._send(
                sock,
                build_data_ack_packet(
                    data_packet.channel, (data_packet.sequence,)
                ),
                address,
            )

            payload = data_packet.payload
            if not payload:
                continue

            app_command = parse_app_command_frame(payload)
            if app_command is not None:
                _command_id, app_payload = app_command
                _LOGGER.debug(
                    "Suntek live command response on channel %s: %s",
                    data_packet.channel,
                    app_payload.decode("utf-8", "replace"),
                )
                continue

            if b"\xff\xd8" not in payload and not logged_non_jpeg:
                _LOGGER.debug(
                    "Suntek live stream returned non-JPEG payload on channel %s: %s",
                    data_packet.channel,
                    payload[:24].hex(),
                )
                logged_non_jpeg = True

            jpg_buffer.extend(payload)
            while True:
                start = jpg_buffer.find(b"\xff\xd8")
                if start < 0:
                    if len(jpg_buffer) > 1024 * 1024:
                        del jpg_buffer[:-2]
                    break
                end = jpg_buffer.find(b"\xff\xd9", start + 2)
                if end < 0:
                    if start:
                        del jpg_buffer[:start]
                    break
                frame = bytes(jpg_buffer[start : end + 2])
                del jpg_buffer[: end + 2]
                yield frame

    @staticmethod
    def _add_peer_candidates(
        candidates: set[tuple[str, int]], peer: tuple[str, int]
    ) -> None:
        host, port = peer
        first = max(1, port - _PUNCH_PORT_SPAN)
        last = min(65535, port + _PUNCH_PORT_SPAN)
        for candidate_port in range(first, last + 1):
            candidates.add((host, candidate_port))
