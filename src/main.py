"""TService local web service template."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import threading
import time
from pathlib import Path

import urllib.error
import urllib.request

from flask import Flask, jsonify, request, send_from_directory

from models import PostRequest, PostResponse

logger = logging.getLogger(__name__)

SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = None

SERVICEHANDLER_HASH: str | None = None
NO_GUI: bool = False

_CONFIG_CACHE: dict | None = None


def _load_configuration() -> dict:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    config_path = Path(__file__).resolve().parent.parent / "resources" / "configuration.json"
    if not config_path.exists():
        raise FileNotFoundError("Configuration file not found.")

    try:
        with open(config_path, "r", encoding="utf-8-sig") as f:
            config = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError("Configuration file contains invalid JSON") from exc

    _CONFIG_CACHE = config
    return config


def _initialize_service_config() -> None:
    global SERVICE_PORT, NO_GUI
    config = _load_configuration()

    configured_port = config.get("port", 49150)
    if isinstance(configured_port, str) and configured_port.isdigit():
        configured_port = int(configured_port)
    if not isinstance(configured_port, int):
        configured_port = 49150
    SERVICE_PORT = configured_port

    NO_GUI = config.get("noGUI", False)


def _get_local_device_addresses() -> set[str]:
    local_addresses: set[str] = set()
    candidate_names = {socket.gethostname(), socket.getfqdn()}

    for candidate_name in candidate_names:
        if not candidate_name:
            continue
        try:
            local_addresses.update(
                address_info[4][0]
                for address_info in socket.getaddrinfo(candidate_name, None)
            )
        except OSError:
            pass
        try:
            local_addresses.update(socket.gethostbyname_ex(candidate_name)[2])
        except OSError:
            pass

    for probe_address in ("8.8.8.8", "1.1.1.1"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as socket_handle:
                socket_handle.connect((probe_address, 80))
                local_addresses.add(socket_handle.getsockname()[0])
        except OSError:
            pass

    normalized_addresses: set[str] = set()
    for address_value in local_addresses:
        try:
            normalized_addresses.add(ipaddress.ip_address(address_value).compressed)
        except ValueError:
            continue

    normalized_addresses.update({"127.0.0.1", "::1"})
    return normalized_addresses


def _is_local_request() -> bool:
    remote_address = request.remote_addr
    if not isinstance(remote_address, str) or not remote_address.strip():
        return False
    try:
        client_ip = ipaddress.ip_address(remote_address.strip())
    except ValueError:
        return False
    if client_ip.is_loopback:
        return True
    return client_ip.compressed in _get_local_device_addresses()


app = Flask(__name__)


@app.before_request
def restrict_to_local_device() -> tuple | None:
    if request.path.startswith("/api/") or (not NO_GUI and (request.path in ("/",) or request.path.startswith(("/ui/", "/css/")))):
        if not _is_local_request():
            return jsonify({"error": "Local device access only."}), 403
    return None


def _options_response(allowed_methods: list[str]) -> tuple:
    response = jsonify({})
    response.headers["Allow"] = ", ".join(allowed_methods)
    response.headers["Access-Control-Allow-Methods"] = ", ".join(allowed_methods)
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response, 200


def _head_response() -> tuple:
    response = jsonify({})
    return response, 200


@app.after_request
def set_connection_header(response):
    content_type = response.headers.get("Content-Type", "")
    if content_type.startswith("text/html"):
        response.headers["Connection"] = "keep-alive"
    else:
        response.headers["Connection"] = "close"
    return response


@app.route("/api/health", methods=["GET", "HEAD", "OPTIONS"])
def health() -> tuple:
    if request.method == "OPTIONS":
        return _options_response(["GET", "HEAD", "OPTIONS"])
    if request.method == "HEAD":
        return _head_response()

    return jsonify({
        "status": "ok",
        "service": "TService",
        "bind_address": SERVICE_HOST,
        "port": SERVICE_PORT,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
    }), 200


def index():
    if request.method == "OPTIONS":
        return _options_response(["GET", "HEAD", "OPTIONS"])
    if request.method == "HEAD":
        return _head_response()
    web_dir = Path(__file__).resolve().parent.parent / "ui" / "pages"
    return send_from_directory(web_dir, "index.html")


def ui_css(filename: str):
    if request.method == "OPTIONS":
        return _options_response(["GET", "HEAD", "OPTIONS"])
    if request.method == "HEAD":
        return _head_response()
    css_dir = Path(__file__).resolve().parent.parent / "ui" / "css"
    return send_from_directory(css_dir, filename)


def _register_ui_routes(app_instance: Flask) -> None:
    if NO_GUI:
        return
    app_instance.add_url_rule("/", methods=["GET", "HEAD", "OPTIONS"], view_func=index)
    app_instance.add_url_rule(
        "/ui/css/<path:filename>",
        methods=["GET", "HEAD", "OPTIONS"],
        view_func=ui_css,
    )


def _send_post_request(request_obj: PostRequest) -> PostResponse:
    try:
        req = urllib.request.Request(
            request_obj.url,
            data=request_obj.body,
            headers=request_obj.headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=request_obj.timeout) as resp:
            body = resp.read().decode("utf-8")
            body_size = len(body)
            headers = dict(resp.headers)
            json_body = None
            try:
                json_body = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                pass
            return PostResponse(
                status_code=resp.status,
                reason=resp.reason,
                body=body,
                body_size=body_size,
                headers=headers,
                json_body=json_body,
            )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        body_size = len(body)
        headers = dict(exc.headers)
        json_body = None
        try:
            json_body = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            pass
        return PostResponse(
            status_code=exc.code,
            reason=str(exc.reason),
            body=body,
            body_size=body_size,
            headers=headers,
            json_body=json_body,
        )


def _register_endpoints_with_servicehandler() -> None:
    global SERVICEHANDLER_HASH
    if not SERVICEHANDLER_HASH:
        return

    config = _load_configuration()
    sh_port = config.get("servicehandlerPort", 49155)

    endpoints = [
        {
            "verb": "GET",
            "path": "/api/health",
            "path_variables": [],
            "body_schema": {},
            "description": "Service health check.",
        },
    ]

    for ep in endpoints:
        try:
            post_req = PostRequest(
                url=f"http://127.0.0.1:{sh_port}/api/register/endpoint",
                body=json.dumps({"hash": SERVICEHANDLER_HASH, **ep}).encode("utf-8"),
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            resp = _send_post_request(post_req)
            if resp.status_code == 201:
                logger.info(f"Registered endpoint: {ep['verb']} {ep['path']}")
            elif resp.status_code == 409:
                logger.debug(f"Endpoint already registered: {ep['verb']} {ep['path']}")
            else:
                logger.warning(f"Failed to register endpoint {ep['verb']} {ep['path']} (HTTP {resp.status_code})")
        except Exception as exc:
            logger.warning(f"Failed to register endpoint {ep['verb']} {ep['path']}: {exc}")


def _servicehandler_keepalive_forever() -> None:
    global SERVICEHANDLER_HASH
    config = _load_configuration()
    sh_port = config.get("servicehandlerPort", 49155)
    service_name = "TService"

    while True:
        time.sleep(15)
        try:
            post_req = PostRequest(
                url=f"http://127.0.0.1:{sh_port}/api/question/service",
                body=json.dumps({"name": service_name}).encode("utf-8"),
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            resp = _send_post_request(post_req)
            if resp.status_code == 200:
                if not SERVICEHANDLER_HASH and isinstance(resp.json_body, dict):
                    SERVICEHANDLER_HASH = resp.json_body.get("hash")
                continue
            if resp.status_code != 404:
                logger.warning(f"ServiceHandler question failed (HTTP {resp.status_code})")
                continue
        except Exception as exc:
            logger.warning(f"ServiceHandler question failed: {exc}")
            continue

        try:
            post_req = PostRequest(
                url=f"http://127.0.0.1:{sh_port}/api/register/service",
                body=json.dumps({
                    "name": service_name,
                    "port": SERVICE_PORT,
                    "starting_script": str(Path(__file__).resolve().parent.parent / "scripts" / ("run.bat" if os.name == "nt" else "run.sh")),
                    "bind_address": SERVICE_HOST,
                    "hostname": socket.gethostname(),
                }).encode("utf-8"),
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            resp = _send_post_request(post_req)
            if resp.status_code == 201 and isinstance(resp.json_body, dict):
                SERVICEHANDLER_HASH = resp.json_body.get("hash")
                logger.info(f"Registered with ServiceHandler, hash={SERVICEHANDLER_HASH[:16] if SERVICEHANDLER_HASH else 'None'}...")
                if SERVICEHANDLER_HASH:
                    _register_endpoints_with_servicehandler()
        except Exception as exc:
            logger.warning(f"ServiceHandler registration attempt failed: {exc}")


if __name__ == "__main__":
    try:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

        _initialize_service_config()
        _register_ui_routes(app)
    except Exception as exc:
        logger.error(f"Failed to load configuration: {exc}")
        exit(1)

    config = _load_configuration()
    if config.get("servicehandlerEnabled", True):
        servicehandler_thread = threading.Thread(
            target=_servicehandler_keepalive_forever,
            name="servicehandler-keepalive",
            daemon=True,
        )
        servicehandler_thread.start()

    try:
        logger.info("=" * 50)
        logger.info("  TService")
        logger.info("=" * 50)
        logger.info(f"Binding to: http://{SERVICE_HOST}:{SERVICE_PORT}")
        logger.info(f"Mode: private (local only)")
        logger.info("Server starting...")

        app.run(host=SERVICE_HOST, port=SERVICE_PORT, debug=False, threaded=True)

    except OSError as exc:
        if "Address already in use" in str(exc):
            logger.error(f"Port {SERVICE_PORT} is already in use. Change the port in resources/configuration.json")
        elif "Permission denied" in str(exc):
            logger.error(f"Permission denied to bind to port {SERVICE_PORT}. Use a port >= 1024 or run with elevated privileges.")
        else:
            logger.error(f"Network binding failed: {exc}")

    except KeyboardInterrupt:
        logger.info("=" * 50)
        logger.info("  Server Stopped")
        logger.info("=" * 50)

    except Exception as exc:
        logger.error(f"Server startup failed: {exc}")
