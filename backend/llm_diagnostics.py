"""Default: print only safe config. --network probes DNS/TLS without model calls."""
import argparse
import json
import socket
import ssl
from urllib.parse import urlsplit
import certifi
from agents.llm_transport import safe_configuration
from config import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()
    result = safe_configuration()
    if args.network:
        host = urlsplit(settings.resolved_llm_base_url or "https://api.openai.com/v1").hostname
        try:
            socket.getaddrinfo(host, 443)
            result["dns"] = "resolved"
            context = ssl.create_default_context(cafile=settings.llm_ca_bundle or certifi.where())
            with socket.create_connection((host, 443), timeout=5) as conn:
                with context.wrap_socket(conn, server_hostname=host):
                    result["tls"] = "verified"
        except socket.gaierror:
            result["failure"] = "dns_failure"
        except (OSError, ssl.SSLError):
            result["failure"] = "tcp_or_tls_failure"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
