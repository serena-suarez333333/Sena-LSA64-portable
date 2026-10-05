"""Create a private local CA and a LAN HTTPS certificate for the demo."""

from __future__ import annotations

import ipaddress
import os
import socket
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _certificate_name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _machine_names() -> list[x509.GeneralName]:
    names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName(socket.gethostname()),
    ]
    addresses = {"127.0.0.1", "::1"}
    try:
        addresses.update(
            result[4][0]
            for result in socket.getaddrinfo(socket.gethostname(), None)
            if result[0] in (socket.AF_INET, socket.AF_INET6)
        )
    except OSError:
        pass

    for address in addresses:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(address)))
        except ValueError:
            continue
    return names


def build_server_context() -> tuple[ssl.SSLContext, bytes]:
    """Return a TLS context and the CA certificate users can trust on phones."""
    app_data = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    certificate_dir = app_data / "SenaDemo" / "certificates"
    certificate_dir.mkdir(parents=True, exist_ok=True)
    ca_key_path = certificate_dir / "local-ca-key.pem"
    ca_certificate_path = certificate_dir / "local-ca.pem"
    server_key_path = certificate_dir / "server-key.pem"
    server_certificate_path = certificate_dir / "server.pem"

    if ca_key_path.exists() and ca_certificate_path.exists():
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        ca_certificate = x509.load_pem_x509_certificate(ca_certificate_path.read_bytes())
    else:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        ca_certificate = (
            x509.CertificateBuilder()
            .subject_name(_certificate_name("Sena Local Demo CA"))
            .issuer_name(_certificate_name("Sena Local Demo CA"))
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(ca_key, hashes.SHA256())
        )
        ca_key_path.write_bytes(
            ca_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        ca_certificate_path.write_bytes(
            ca_certificate.public_bytes(serialization.Encoding.PEM)
        )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(_certificate_name(socket.gethostname()))
        .issuer_name(ca_certificate.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(_machine_names()), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    server_key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    server_certificate_path.write_bytes(
        server_certificate.public_bytes(serialization.Encoding.PEM)
    )

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(server_certificate_path, server_key_path)
    return context, ca_certificate.public_bytes(serialization.Encoding.PEM)