"""P2P protocol pieces used by Suntek LTE cameras."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import socket
import time
from typing import Final

PPCS_PORT: Final = 32100
DEFAULT_CONNECT_TIMEOUT: Final = 240.0
DEFAULT_REQUEST_INTERVAL: Final = 1.0

PACKET_HELLO: Final = 0x00
PACKET_HELLO_ACK: Final = 0x01
PACKET_P2P_REQUEST: Final = 0x20
PACKET_P2P_REQUEST_ACK: Final = 0x21
PACKET_PUNCH_TO: Final = 0x40
PACKET_PUNCH: Final = 0x41
PACKET_P2P_READY: Final = 0x42
PACKET_LIST_REQUEST: Final = 0x67
PACKET_LIST_RESPONSE: Final = 0x69
PACKET_RELAY_HELLO: Final = 0x70
PACKET_RELAY_HELLO_ACK: Final = 0x71
PACKET_RELAY_PORT: Final = 0x72
PACKET_RELAY_PORT_ACK: Final = 0x73
PACKET_RELAY_REQUEST: Final = 0x80
PACKET_RELAY_REQUEST_ACK: Final = 0x81
PACKET_RELAY_TO: Final = 0x82
PACKET_RELAY_PACKET: Final = 0x83
PACKET_RELAY_READY: Final = 0x84
PACKET_DATA: Final = 0xD0
PACKET_DATA_ACK: Final = 0xD1
PACKET_ALIVE: Final = 0xE0
PACKET_ALIVE_ACK: Final = 0xE1

P2P_REQUEST_ACCEPTED: Final = 0x00
APP_COMMAND_CHANNEL: Final = 1
APP_VIDEO_COMMAND_ID: Final = 3

_CONTROL_MAGIC: Final = 0xF1
_APP_COMMAND_MAGIC: Final = b"\xA0\xAF\xAF\xAF"
_APP_COMMAND_FOOTER: Final = b"\xF4\xF3\xF2\xF1"
_DID_RE: Final = re.compile(r"^([A-Z]{1,7})-(\d{1,10})-([A-Z0-9]{1,7})$")

_DECODE_TABLE: Final = bytes.fromhex(
    "4959433db5bf6da347534f6165e371e9677f02030badb3892b2f35c16b8b"
    "959711e5a70deff1050783fb9d3bc5c713171d1f2529d3df"
)

_P2P_TABLE: Final = bytes.fromhex(
    "7c9ce84a13dedcb22f2123e4307b3d8cbc0b270c3cf79ae7087196009785"
    "efc11fc4dba1c2ebd901faba3b05b81587832872d18b5ad6da9358feaacc"
    "6e1bf0a388ab43c00db545384f502266207f075b14981d9ba72ab9a8cbf"
    "1fc4947063eb10e043a945eee541134dd4df9ecc7c9e3781a6f706ba4b"
    "da95dd5f8e5bb26af4237d8e1020aae5f1cc573094e6924906d12b319"
    "ad748a2940f52dbea559e0f479d24bce8982488425c6912ba2fb8fe9"
    "a6b09e3f65f603312eac0f952c5ced39b7336c567eb4a0fd7a815351"
    "868d9f77ff6a80dfe2bf10d775645776f355cdd0c818e6364162cf99"
    "f2324c67606192cad3ea637d16b68ed46835c3529d46441e17"
)

_TOPVIEW_INIT: Final = (
    "EEGDFHBAKBIFGOJFFPHKFPEAGINKHPMJHGFPBADPAFJCLEKADDAHCEPMGHLEIELD"
    "ACNIKNDCPONBBACBIJ:TopViewP2P"
)
_VIEWKING_CN_INIT: Final = (
    "EEGDFHBAKBIFGGJLEKHAFEEKGCNAHFMDHMFEBODBAPJAKAKLDOADDFPFGIKGIJL"
    "LAINCKBDIOPNPBDCJIB:ViewKing"
)
_VIEWKING_GLOBAL_INIT: Final = (
    "EIHGFOBBKIIMGMJCFIHNFAEGGONAGMMGHIFIALDIACIKKHKOCABADNOHHEKEJEK"
    "EBCNHLLCDPBNOAG:ViewKing"
)


class SuntekP2PError(Exception):
    """Raised when a P2P packet or DID cannot be handled."""


@dataclass(frozen=True, slots=True)
class P2PProfile:
    """P2P bootstrap profile decoded from the native init strings."""

    name: str
    key: str
    servers: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class P2PDid:
    """Suntek P2P DID split into the native packet fields."""

    prefix: str
    number: int
    suffix: str

    @property
    def value(self) -> str:
        """Return the canonical dashed DID."""
        return f"{self.prefix}-{self.number}-{self.suffix}"


@dataclass(frozen=True, slots=True)
class P2PControlPacket:
    """Decoded F1 control packet."""

    packet_type: int
    payload: bytes


@dataclass(frozen=True, slots=True)
class P2PHelloAck:
    """Public UDP endpoint reported by a P2P bootstrap server."""

    server: tuple[str, int]
    family: int
    public_address: tuple[str, int]


@dataclass(frozen=True, slots=True)
class P2PRequestAck:
    """Result of asking a bootstrap server to connect to a DID."""

    server: tuple[str, int]
    status: int
    status_text: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class P2PRelayPortAck:
    """Relay server session number and port pair."""

    server: tuple[str, int]
    relay_number: int
    relay_port: int


@dataclass(frozen=True, slots=True)
class P2PRelayTo:
    """Relay destination request from a bootstrap server."""

    server: tuple[str, int]
    relay_address: tuple[str, int]
    relay_number: int


@dataclass(frozen=True, slots=True)
class P2PDataPacket:
    """Application data packet carried over a PPCS DRW channel."""

    channel: int
    sequence: int
    payload: bytes


@dataclass(frozen=True, slots=True)
class P2PProbeResult:
    """Single bootstrap probe result."""

    profile: P2PProfile
    local_address: tuple[str, int]
    hello: P2PHelloAck | None
    request: P2PRequestAck | None
    punch_endpoints: tuple[tuple[str, int], ...] = ()


def decode_init_string(value: str) -> tuple[tuple[str, ...], str]:
    """Decode the server list and key from an APK init string."""
    encoded, separator, key = value.partition(":")
    if not encoded or not separator or not key:
        raise SuntekP2PError("Invalid P2P init string")
    if len(encoded) % 2:
        raise SuntekP2PError("Invalid P2P init string length")

    decoded = bytearray()
    rolling_xor = 0x39
    for index in range(0, len(encoded), 2):
        first = ord(encoded[index])
        second = ord(encoded[index + 1])
        pair = (second + (first << 4) - 0x451) & 0xFF
        value_byte = (
            rolling_xor
            ^ pair
            ^ _DECODE_TABLE[(index // 2) % len(_DECODE_TABLE)]
        )
        decoded.append(value_byte)
        rolling_xor ^= value_byte

    servers = tuple(
        item.strip()
        for item in decoded.decode("ascii", errors="ignore").split(",")
        if item.strip()
    )
    if not servers:
        raise SuntekP2PError("P2P init string did not contain servers")
    return servers, key.strip()


def build_profile(name: str, init_string: str) -> P2PProfile:
    """Build a bootstrap profile from a native init string."""
    servers, key = decode_init_string(init_string)
    return P2PProfile(
        name=name,
        key=key,
        servers=tuple((server, PPCS_PORT) for server in servers),
    )


DEFAULT_PROFILES: Final = (
    build_profile("ViewKing global", _VIEWKING_GLOBAL_INIT),
    build_profile("ViewKing China", _VIEWKING_CN_INIT),
    build_profile("TopViewP2P", _TOPVIEW_INIT),
)


def profiles_for_device_api(
    device_api: str | None, *, include_fallback: bool = True
) -> tuple[P2PProfile, ...]:
    """Return bootstrap profiles ordered for the device API string."""
    if not device_api:
        return DEFAULT_PROFILES

    _prefix, _separator, key = device_api.partition(":")
    key = (key or device_api).strip().lower()
    preferred = [profile for profile in DEFAULT_PROFILES if profile.key.lower() == key]
    if preferred and not include_fallback:
        return tuple(preferred)

    fallback = [profile for profile in DEFAULT_PROFILES if profile not in preferred]
    return tuple([*preferred, *fallback])


def parse_did(value: str) -> P2PDid:
    """Parse a Suntek P2P DID such as VIST-138396-LXEXM."""
    normalised = normalise_did(value)
    match = _DID_RE.match(normalised)
    if not match:
        raise SuntekP2PError(f"Invalid P2P DID: {value}")

    prefix, number_raw, suffix = match.groups()
    number = int(number_raw)
    if number > 0xFFFFFFFF:
        raise SuntekP2PError(f"P2P DID number is too large: {value}")
    return P2PDid(prefix=prefix, number=number, suffix=suffix)


def normalise_did(value: str) -> str:
    """Return a dashed uppercase DID where possible."""
    value = re.sub(r"\s+", "", value or "").upper()
    if value.count("-") == 2:
        return value

    match = re.match(r"^([A-Z]{1,7})-?(\d{1,10})-?([A-Z0-9]{1,7})$", value)
    if not match:
        return value
    return "-".join(match.groups())


def build_control_packet(packet_type: int, payload: bytes = b"") -> bytes:
    """Build a native F1 control packet."""
    if not 0 <= packet_type <= 0xFF:
        raise SuntekP2PError(f"Invalid packet type: {packet_type}")
    if len(payload) > 0xFFFF:
        raise SuntekP2PError("P2P payload is too large")
    return (
        bytes((_CONTROL_MAGIC, packet_type))
        + len(payload).to_bytes(2, "big")
        + payload
    )


def parse_control_packet(data: bytes) -> P2PControlPacket:
    """Parse a decrypted F1 control packet."""
    if len(data) < 4 or data[0] != _CONTROL_MAGIC:
        raise SuntekP2PError("Invalid P2P control packet")

    length = int.from_bytes(data[2:4], "big")
    if len(data) - 4 != length:
        raise SuntekP2PError("Invalid P2P control packet length")
    return P2PControlPacket(packet_type=data[1], payload=data[4:])


def build_hello_packet() -> bytes:
    """Build the plain Hello packet sent to bootstrap servers."""
    return build_control_packet(PACKET_HELLO)


def build_p2p_request_packet(
    did: str | P2PDid,
    local_port: int,
    local_ip: str = "0.0.0.0",
) -> bytes:
    """Build the plain P2PReq packet for a DID."""
    parsed = did if isinstance(did, P2PDid) else parse_did(did)
    if not 0 <= local_port <= 0xFFFF:
        raise SuntekP2PError(f"Invalid local UDP port: {local_port}")

    payload = bytearray(0x24)
    payload[0:7] = _fixed_ascii(parsed.prefix, 7)
    payload[8:12] = parsed.number.to_bytes(4, "big")
    payload[12:19] = _fixed_ascii(parsed.suffix, 7)
    payload[20:28] = encode_sockaddr(local_ip, local_port)
    return build_control_packet(PACKET_P2P_REQUEST, bytes(payload))


def build_p2p_ready_packet(did: str | P2PDid) -> bytes:
    """Build the plain P2PRdy packet used after a punch succeeds."""
    parsed = did if isinstance(did, P2PDid) else parse_did(did)
    payload = bytearray(0x14)
    payload[0:7] = _fixed_ascii(parsed.prefix, 7)
    payload[8:12] = parsed.number.to_bytes(4, "big")
    payload[12:19] = _fixed_ascii(parsed.suffix, 7)
    return build_control_packet(PACKET_P2P_READY, bytes(payload))


def build_list_request_packet(did: str | P2PDid) -> bytes:
    """Build ListReq1, which asks bootstrap servers for relay candidates."""
    parsed = did if isinstance(did, P2PDid) else parse_did(did)
    payload = bytearray(0x14)
    payload[0:7] = _fixed_ascii(parsed.prefix, 7)
    payload[8:12] = parsed.number.to_bytes(4, "big")
    payload[12:19] = _fixed_ascii(parsed.suffix, 7)
    return build_control_packet(PACKET_LIST_REQUEST, bytes(payload))


def build_relay_hello_packet() -> bytes:
    """Build RlyHello, sent to relay candidates from ListReq1."""
    return build_control_packet(PACKET_RELAY_HELLO)


def build_relay_port_packet() -> bytes:
    """Build RlyPort, sent after a relay server acknowledges RlyHello."""
    return build_control_packet(PACKET_RELAY_PORT)


def build_relay_request_packet(
    did: str | P2PDid,
    relay_address: tuple[str, int],
    relay_number: int,
) -> bytes:
    """Build RlyReq for a chosen relay server."""
    parsed = did if isinstance(did, P2PDid) else parse_did(did)
    payload = bytearray(0x28)
    payload[0:7] = _fixed_ascii(parsed.prefix, 7)
    payload[8:12] = parsed.number.to_bytes(4, "big")
    payload[12:19] = _fixed_ascii(parsed.suffix, 7)
    payload[20:28] = encode_sockaddr(*relay_address)
    payload[36:40] = relay_number.to_bytes(4, "big")
    return build_control_packet(PACKET_RELAY_REQUEST, bytes(payload))


def build_relay_packet(
    did: str | P2PDid,
    relay_number: int,
    *,
    mode: int = 1,
) -> bytes:
    """Build RlyPkt in response to a RlyTo packet."""
    parsed = did if isinstance(did, P2PDid) else parse_did(did)
    if not 0 <= mode <= 0xFF:
        raise SuntekP2PError(f"Invalid relay mode: {mode}")

    payload = bytearray(0x1C)
    payload[0:4] = relay_number.to_bytes(4, "big")
    payload[4:11] = _fixed_ascii(parsed.prefix, 7)
    payload[12:16] = parsed.number.to_bytes(4, "big")
    payload[16:23] = _fixed_ascii(parsed.suffix, 7)
    payload[24] = mode
    return build_control_packet(PACKET_RELAY_PACKET, bytes(payload))


def build_alive_packet() -> bytes:
    """Build a session keepalive packet."""
    return build_control_packet(PACKET_ALIVE)


def build_punch_packet(did: str | P2PDid) -> bytes:
    """Build the plain Punch packet sent to a peer endpoint."""
    parsed = did if isinstance(did, P2PDid) else parse_did(did)
    payload = bytearray(0x14)
    payload[0:7] = _fixed_ascii(parsed.prefix, 7)
    payload[8:12] = parsed.number.to_bytes(4, "big")
    payload[12:19] = _fixed_ascii(parsed.suffix, 7)
    return build_control_packet(PACKET_PUNCH, bytes(payload))


def encode_sockaddr(host: str, port: int) -> bytes:
    """Encode IPv4 host/port like the native sockaddr serializer."""
    if not 0 <= port <= 0xFFFF:
        raise SuntekP2PError(f"Invalid UDP port: {port}")
    return (
        int(socket.AF_INET).to_bytes(2, "big")
        + port.to_bytes(2, "big")[::-1]
        + socket.inet_aton(host)[::-1]
    )


def parse_sockaddr(payload: bytes) -> tuple[str, int]:
    """Parse the native sockaddr payload used by HelloAck/PunchTo."""
    if len(payload) < 8:
        raise SuntekP2PError("Invalid sockaddr payload")
    family = int.from_bytes(payload[0:2], "big")
    if family != socket.AF_INET:
        raise SuntekP2PError(f"Unsupported address family: {family}")
    port = int.from_bytes(payload[2:4][::-1], "big")
    host = socket.inet_ntoa(payload[4:8][::-1])
    return host, port


def build_data_packet(channel: int, sequence: int, payload: bytes) -> bytes:
    """Build a plain DRW data packet for an established PPCS session."""
    if not 0 <= channel <= 7:
        raise SuntekP2PError(f"Invalid data channel: {channel}")
    if not 0 <= sequence <= 0xFFFF:
        raise SuntekP2PError(f"Invalid data sequence: {sequence}")
    if len(payload) > 0xFFFF - 4:
        raise SuntekP2PError("P2P data payload is too large")

    inner = (
        bytes((PACKET_DATA_ACK, channel))
        + sequence.to_bytes(2, "big")
        + payload
    )
    return build_control_packet(PACKET_DATA, inner)


def build_data_ack_packet(channel: int, sequences: tuple[int, ...]) -> bytes:
    """Build a DRWAck packet for received data sequences."""
    if not 0 <= channel <= 7:
        raise SuntekP2PError(f"Invalid data channel: {channel}")
    if len(sequences) > 0x51:
        raise SuntekP2PError("Too many P2P data acknowledgements")

    inner = bytearray((PACKET_DATA_ACK, channel))
    inner.extend(len(sequences).to_bytes(2, "big"))
    for sequence in sequences:
        if not 0 <= sequence <= 0xFFFF:
            raise SuntekP2PError(f"Invalid data sequence: {sequence}")
        inner.extend(sequence.to_bytes(2, "big"))
    return build_control_packet(PACKET_DATA_ACK, bytes(inner))


def parse_data_packet(payload: bytes) -> P2PDataPacket:
    """Parse the payload of a DRW data packet."""
    if len(payload) < 4 or payload[0] != PACKET_DATA_ACK:
        raise SuntekP2PError("Invalid P2P data payload")
    channel = payload[1]
    if channel > 7:
        raise SuntekP2PError(f"Invalid P2P data channel: {channel}")
    return P2PDataPacket(
        channel=channel,
        sequence=int.from_bytes(payload[2:4], "big"),
        payload=payload[4:],
    )


def build_app_command_frame(
    command_id: int,
    payload: bytes,
    *,
    transaction_id: int | None = None,
) -> bytes:
    """Wrap an application JSON command like the native lxIpc command protocol."""
    if not 0 <= command_id <= 0xFF:
        raise SuntekP2PError(f"Invalid application command id: {command_id}")

    if transaction_id is None:
        transaction_id = int(time.monotonic() * 1000) & 0xFFFFFFFF
    if not 0 <= transaction_id <= 0xFFFFFFFF:
        raise SuntekP2PError(f"Invalid transaction id: {transaction_id}")

    if not payload.endswith(b"\x00"):
        payload += b"\x00"
    if len(payload) > 0xFFFFFFFF:
        raise SuntekP2PError("Application command payload is too large")

    return (
        _APP_COMMAND_MAGIC
        + bytes((command_id, 0))
        + transaction_id.to_bytes(4, "little")
        + (b"\x00" * 12)
        + len(payload).to_bytes(4, "little")
        + payload
        + _APP_COMMAND_FOOTER
    )


def parse_app_command_frame(payload: bytes) -> tuple[int, bytes] | None:
    """Return command id and payload from a native lxIpc command frame."""
    if (
        len(payload) < 30
        or not payload.startswith(_APP_COMMAND_MAGIC)
        or not payload.endswith(_APP_COMMAND_FOOTER)
    ):
        return None

    length = int.from_bytes(payload[22:26], "little")
    data = payload[26:-4]
    if len(data) != length:
        start = data.find(b"{")
        end = data.rfind(b"}")
        if start < 0 or end < start:
            return None
        data = data[start : end + 1]
        return payload[4], data
    return payload[4], data.rstrip(b"\x00")


def build_login_command(password_hash: str) -> bytes:
    """Build the Suntek application login JSON sent as native command id 3."""
    return _json_command({"cmd": "LoginDev", "pwd": password_hash})


def build_open_video_command(
    password_hash: str, *, user_id: int = 0, state: int = 1
) -> bytes:
    """Build the Suntek OpenVideo JSON sent after application login."""
    return _json_command(
        {
            "cmd": "OpenVideo",
            "pwd": password_hash,
            "userid": user_id,
            "state": state,
        }
    )


def parse_hello_ack(server: tuple[str, int], payload: bytes) -> P2PHelloAck:
    """Parse the payload of a HelloAck packet."""
    if len(payload) < 8:
        raise SuntekP2PError("Invalid HelloAck payload")
    family = int.from_bytes(payload[0:2], "big")
    return P2PHelloAck(
        server=server,
        family=family,
        public_address=parse_sockaddr(payload),
    )


def parse_p2p_request_ack(server: tuple[str, int], payload: bytes) -> P2PRequestAck:
    """Parse a P2PReqAck payload."""
    if not payload:
        raise SuntekP2PError("Invalid P2PReqAck payload")
    status = payload[0]
    return P2PRequestAck(
        server=server,
        status=status,
        status_text=p2p_request_status_text(status),
        payload=payload,
    )


def parse_list_response(payload: bytes) -> tuple[tuple[str, int], ...]:
    """Parse a ListReq1 response containing native relay sockaddr entries."""
    if not payload:
        raise SuntekP2PError("Invalid ListReq response")

    count = payload[0]
    offset = 4
    entries: list[tuple[str, int]] = []
    for _index in range(count):
        if len(payload) < offset + 8:
            break
        entries.append(parse_sockaddr(payload[offset : offset + 8]))
        offset += 16
    return tuple(entries)


def parse_relay_port_ack(
    server: tuple[str, int], payload: bytes
) -> P2PRelayPortAck:
    """Parse a RlyPortAck packet."""
    if len(payload) < 6:
        raise SuntekP2PError("Invalid RlyPortAck payload")
    return P2PRelayPortAck(
        server=server,
        relay_number=int.from_bytes(payload[0:4], "big"),
        relay_port=int.from_bytes(payload[4:6], "big"),
    )


def parse_relay_to(server: tuple[str, int], payload: bytes) -> P2PRelayTo:
    """Parse a RlyTo packet."""
    if len(payload) < 20:
        raise SuntekP2PError("Invalid RlyTo payload")
    return P2PRelayTo(
        server=server,
        relay_address=parse_sockaddr(payload[0:8]),
        relay_number=int.from_bytes(payload[16:20], "big"),
    )


def p2p_request_status_text(status: int) -> str:
    """Return a readable label for known P2PReqAck status bytes."""
    return {
        0x00: "accepted",
        0xFC: "server rejected the request",
        0xFD: "device is not ready",
        0xFE: "waiting for device",
        0xFF: "request failed",
    }.get(status, f"unknown status 0x{status:02x}")


def p2p_encrypt(key: str, data: bytes) -> bytes:
    """Encrypt bytes with the native PPCS proprietary cipher."""
    key_bytes = _derive_key(key)
    if key_bytes is None:
        return data

    output = bytearray(len(data))
    previous = 0
    for index, value in enumerate(data):
        encrypted = _P2P_TABLE[(previous + key_bytes[previous & 3]) & 0xFF] ^ value
        output[index] = encrypted
        previous = encrypted
    return bytes(output)


def p2p_decrypt(key: str, data: bytes) -> bytes:
    """Decrypt bytes with the native PPCS proprietary cipher."""
    key_bytes = _derive_key(key)
    if key_bytes is None:
        return data

    output = bytearray(len(data))
    previous = 0
    for index, encrypted in enumerate(data):
        output[index] = (
            _P2P_TABLE[(previous + key_bytes[previous & 3]) & 0xFF] ^ encrypted
        )
        previous = encrypted
    return bytes(output)


class SuntekP2PClient:
    """Small blocking P2P bootstrap client.

    The full native SDK keeps several UDP/TCP threads alive after bootstrap. This
    class intentionally covers the deterministic bootstrap pieces first so they can
    be called from Home Assistant with async_add_executor_job.
    """

    def __init__(
        self,
        did: str,
        device_api: str | None = None,
        *,
        timeout: float = DEFAULT_CONNECT_TIMEOUT,
        request_interval: float = DEFAULT_REQUEST_INTERVAL,
        include_fallback_profiles: bool = False,
        bind_host: str = "0.0.0.0",
        local_ip: str = "0.0.0.0",
    ) -> None:
        self.did = parse_did(did)
        self.profiles = profiles_for_device_api(
            device_api, include_fallback=include_fallback_profiles
        )
        self.timeout = timeout
        self.request_interval = request_interval
        self.bind_host = bind_host
        self.local_ip = local_ip

    def probe(
        self,
        *,
        request_session: bool = True,
        total_timeout: float | None = None,
        stop_on_statuses: set[int] | None = None,
    ) -> list[P2PProbeResult]:
        """Probe bootstrap servers and optionally ask for a DID session."""
        results: list[P2PProbeResult] = []
        deadline = time.monotonic() + (total_timeout or self.timeout)
        stop_on_statuses = (
            {P2P_REQUEST_ACCEPTED} if stop_on_statuses is None else stop_on_statuses
        )

        for profile in self.profiles:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            results.extend(
                self._probe_profile(
                    profile,
                    request_session=request_session,
                    timeout=remaining,
                    stop_on_statuses=stop_on_statuses,
                )
            )
            if _has_stop_status(results, stop_on_statuses):
                break

        return results

    def _probe_profile(
        self,
        profile: P2PProfile,
        *,
        request_session: bool,
        timeout: float,
        stop_on_statuses: set[int],
    ) -> list[P2PProbeResult]:
        results: list[P2PProbeResult] = []
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((self.bind_host, 0))
            sock.settimeout(0.2)
            local_host, local_port = sock.getsockname()
            local_address = (local_host, int(local_port))

            hello_packet = p2p_encrypt(profile.key, build_hello_packet())
            for server in profile.servers:
                sock.sendto(hello_packet, server)

            deadline = time.monotonic() + timeout
            hello_by_server: dict[tuple[str, int], P2PHelloAck] = {}
            request_by_server: dict[tuple[str, int], P2PRequestAck] = {}
            punch_by_server: dict[tuple[str, int], list[tuple[str, int]]] = {}
            next_request_at = 0.0
            stop_requested = False

            while time.monotonic() < deadline and not stop_requested:
                now = time.monotonic()
                if request_session and hello_by_server and now >= next_request_at:
                    request_packet = build_p2p_request_packet(
                        self.did,
                        local_port=local_port,
                        local_ip=self.local_ip,
                    )
                    encrypted_request = p2p_encrypt(profile.key, request_packet)
                    for server in hello_by_server:
                        sock.sendto(encrypted_request, server)
                    next_request_at = now + self.request_interval

                try:
                    encrypted, server = sock.recvfrom(0x5A0)
                except TimeoutError:
                    continue

                try:
                    packet = parse_control_packet(p2p_decrypt(profile.key, encrypted))
                except SuntekP2PError:
                    continue

                if packet.packet_type == PACKET_HELLO_ACK:
                    hello = parse_hello_ack(server, packet.payload)
                    hello_by_server[server] = hello
                    next_request_at = 0.0
                    continue

                if packet.packet_type == PACKET_P2P_REQUEST_ACK:
                    request = parse_p2p_request_ack(server, packet.payload)
                    request_by_server[server] = request
                    stop_requested = request.status in stop_on_statuses
                    continue

                if packet.packet_type == PACKET_PUNCH_TO:
                    punch_by_server.setdefault(server, []).append(
                        parse_sockaddr(packet.payload)
                    )

            servers = sorted(
                set(
                    [
                        *profile.servers,
                        *hello_by_server,
                        *request_by_server,
                        *punch_by_server,
                    ]
                )
            )
            for server in servers:
                hello = hello_by_server.get(server)
                request = request_by_server.get(server)
                punch_endpoints = tuple(punch_by_server.get(server, ()))
                if hello or request or punch_endpoints:
                    results.append(
                        P2PProbeResult(
                            profile=profile,
                            local_address=local_address,
                            hello=hello,
                            request=request,
                            punch_endpoints=punch_endpoints,
                        )
                    )
        return results


def _derive_key(key: str) -> bytes | None:
    key_bytes = key.encode("ascii", errors="ignore")[:20]
    if not key_bytes:
        return None

    total = sum(key_bytes) & 0xFF
    inverse = (-sum(key_bytes)) & 0xFF
    thirds = sum(value // 3 for value in key_bytes) & 0xFF
    xored = 0
    for value in key_bytes:
        xored ^= value
    return bytes((total, inverse, thirds, xored & 0xFF))


def _fixed_ascii(value: str, length: int) -> bytes:
    data = value.encode("ascii", errors="ignore")[:length]
    return data + b"\x00" * (length - len(data))


def _json_command(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _has_stop_status(
    results: list[P2PProbeResult], stop_on_statuses: set[int]
) -> bool:
    return any(
        result.request is not None and result.request.status in stop_on_statuses
        for result in results
    )
