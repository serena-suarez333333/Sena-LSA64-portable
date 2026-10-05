"""Local web app and WebSocket camera stream."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections import deque
from functools import lru_cache, partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from ssl import SSLContext
from threading import Thread
from typing import Any
from urllib.parse import urlsplit

import numpy as np
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from certificates import build_server_context
from detector import HolisticDetector, cv2, detect_gesture
from gesture_model import classify
from lsa64_model import FRAME_COUNT, LSA64Classifier, frame_features
from utils.mapping import GESTURE_HINTS, GESTURE_LABELS

HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8000
WEBSOCKET_HOST = "0.0.0.0"
WEBSOCKET_PORT = 8765
HTTPS_PORT = 8443
SECURE_WEBSOCKET_PORT = 8766
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
LSA64_MODEL_PATH = Path(__file__).resolve().parent / "models" / "lsa64.npz"
logger = logging.getLogger("sign-translator")


@lru_cache(maxsize=1)
def load_lsa64_classifier() -> LSA64Classifier | None:
	if not LSA64_MODEL_PATH.is_file():
		return None
	return LSA64Classifier.load(LSA64_MODEL_PATH)


def make_frontend_handler(ca_certificate: bytes) -> Any:
	class FrontendRequestHandler(SimpleHTTPRequestHandler):
		def __init__(self, *args: Any, **kwargs: Any) -> None:
			self._ca_certificate = ca_certificate
			super().__init__(*args, **kwargs)

		def do_GET(self) -> None:
			if urlsplit(self.path).path == "/sena-local-ca.crt":
				self.send_response(200)
				self.send_header("Content-Type", "application/x-x509-ca-cert")
				self.send_header("Content-Disposition", "attachment; filename=SenaLocalCA.crt")
				self.send_header("Content-Length", str(len(self._ca_certificate)))
				self.end_headers()
				self.wfile.write(self._ca_certificate)
				return
			super().do_GET()

	return partial(FrontendRequestHandler, directory=str(FRONTEND_DIR))


async def _send_error(websocket: ServerConnection, message: str) -> None:
	try:
		await websocket.send(json.dumps({"type": "error", "message": message}))
	except ConnectionClosed:
		pass


async def handle_camera(websocket: ServerConnection) -> None:
	if cv2 is None:
		await _send_error(websocket, "No se pudo cargar OpenCV. Revisa las dependencias.")
		return

	detector: HolisticDetector | None = None
	try:
		lsa64_classifier = load_lsa64_classifier()
		if lsa64_classifier is None:
			logger.info("No hay modelo LSA64; se usa el clasificador heurístico de demostración")
		detector = await asyncio.to_thread(HolisticDetector)
		await websocket.send(json.dumps({"type": "status", "state": "detector_ready"}))
		candidate: str | None = None
		candidate_frames = 0
		active_gesture: str | None = None
		feature_window: deque[Any] = deque(maxlen=FRAME_COUNT)

		async for frame_bytes in websocket:
			if not isinstance(frame_bytes, bytes):
				await _send_error(websocket, "Se esperaba un fotograma JPEG de la cámara.")
				continue

			frame = cv2.imdecode(np.frombuffer(frame_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
			if frame is None:
				await _send_error(websocket, "No se pudo decodificar el fotograma recibido.")
				continue

			landmarks, annotated = await asyncio.to_thread(detect_gesture, frame, detector)
			if lsa64_classifier is None:
				gesture_id = classify(landmarks)
			elif landmarks["left_hand"] or landmarks["right_hand"]:
				feature_window.append(frame_features(landmarks))
				gesture_id = (
					await asyncio.to_thread(lsa64_classifier.classify, list(feature_window))
					if len(feature_window) == FRAME_COUNT
					else None
				)
			else:
				feature_window.clear()
				gesture_id = None
			if gesture_id == candidate:
				candidate_frames += 1
			else:
				candidate = gesture_id
				candidate_frames = 1

			if gesture_id is None:
				active_gesture = None
			elif candidate_frames >= 4:
				active_gesture = gesture_id

			encoded, buffer = cv2.imencode(
				".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75]
			)
			if not encoded:
				continue

			if active_gesture and active_gesture.startswith("lsa64_"):
				gesture_label, gesture_hint = lsa64_classifier.label(active_gesture)
			else:
				gesture_label = GESTURE_LABELS.get(active_gesture)
				gesture_hint = GESTURE_HINTS.get(active_gesture)

			payload: dict[str, Any] = {
				"type": "frame",
				"image": base64.b64encode(buffer).decode("ascii"),
				"gesture": gesture_label,
				"gesture_id": active_gesture,
				"gesture_hint": gesture_hint,
				"stable_frames": min(candidate_frames, 4) if active_gesture else 0,
				"hands_visible": bool(landmarks["left_hand"] or landmarks["right_hand"]),
			}
			await websocket.send(json.dumps(payload))
	except ConnectionClosed:
		logger.info("El cliente cerró el flujo de cámara")
	except Exception as error:
		logger.exception("Error procesando la cámara")
		await _send_error(websocket, f"No se pudo iniciar el detector: {error}")
	finally:
		if detector is not None:
			await asyncio.to_thread(detector.close)


async def serve_websocket(port: int, tls_context: SSLContext | None = None) -> None:
	async with serve(
		handle_camera,
		WEBSOCKET_HOST,
		port,
		ssl=tls_context,
		ping_interval=20,
		ping_timeout=20,
		max_size=4_194_304,
	):
		logger.info("WebSocket escuchando en todas las interfaces (puerto %s)", port)
		await asyncio.Future()


async def run_websocket_servers(tls_context: SSLContext) -> None:
	await asyncio.gather(
		serve_websocket(WEBSOCKET_PORT),
		serve_websocket(SECURE_WEBSOCKET_PORT, tls_context),
	)


def main() -> None:
	logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
	tls_context, ca_pem = build_server_context()
	ca_certificate = x509.load_pem_x509_certificate(ca_pem)
	ca_der = ca_certificate.public_bytes(serialization.Encoding.DER)
	ca_fingerprint = ca_certificate.fingerprint(hashes.SHA256()).hex(":").upper()
	handler = make_frontend_handler(ca_der)
	http_server = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), handler)
	https_server = ThreadingHTTPServer((HTTP_HOST, HTTPS_PORT), handler)
	https_server.socket = tls_context.wrap_socket(https_server.socket, server_side=True)
	Thread(target=http_server.serve_forever, daemon=True).start()
	Thread(target=https_server.serve_forever, daemon=True).start()
	logger.info("Interfaz local: http://127.0.0.1:%s", HTTP_PORT)
	logger.info("Certificado CA SHA-256: %s", ca_fingerprint)
	logger.info("HTTPS para teléfonos: https://<IP-LAN>:%s", HTTPS_PORT)
	logger.info("Descarga CA: http://<IP-LAN>:%s/sena-local-ca.crt", HTTP_PORT)

	try:
		asyncio.run(run_websocket_servers(tls_context))
	except KeyboardInterrupt:
		logger.info("Servidor detenido")
	finally:
		http_server.shutdown()
		https_server.shutdown()
		http_server.server_close()
		https_server.server_close()


if __name__ == "__main__":
	main()
