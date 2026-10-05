"""Set up the portable app environment and run the local server."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_ROOT = ROOT / ".venv"
VENV_PYTHON = VENV_ROOT / "Scripts" / "python.exe"
DEPENDENCIES_READY = VENV_ROOT / ".dependencies-ready"
SERVER_URL = "http://127.0.0.1:8000/"


def prepare_environment() -> None:
	if not (3, 10) <= sys.version_info[:2] <= (3, 12):
		raise RuntimeError("Se requiere Python 3.10, 3.11 o 3.12 de 64 bits.")

	if not VENV_PYTHON.exists():
		print("Preparando el entorno local de Python...", flush=True)
		subprocess.run([sys.executable, "-m", "venv", str(VENV_ROOT)], check=True)

	if not DEPENDENCIES_READY.exists():
		print("Instalando dependencias (se necesita Internet la primera vez)...", flush=True)
		subprocess.run(
			[
				str(VENV_PYTHON),
				"-m",
				"pip",
				"install",
				"-r",
				str(ROOT / "backend" / "requirements.txt"),
			],
			check=True,
		)
		DEPENDENCIES_READY.touch()


def wait_for_server(process: subprocess.Popen[bytes], timeout: float = 60.0) -> None:
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if process.poll() is not None:
			raise RuntimeError(
				f"El servidor terminó antes de iniciar (código {process.returncode})."
			)
		try:
			with urllib.request.urlopen(SERVER_URL, timeout=2):
				return
		except (OSError, urllib.error.URLError):
			time.sleep(0.5)
	raise TimeoutError("El servidor no respondió en 60 segundos.")


def main() -> None:
	prepare_environment()
	server = subprocess.Popen(
		[str(VENV_PYTHON), "-u", str(ROOT / "backend" / "app.py")],
		cwd=ROOT,
	)
	try:
		wait_for_server(server)
		print(f"Aplicación lista: {SERVER_URL}", flush=True)
		webbrowser.open(SERVER_URL)
		server.wait()
	except KeyboardInterrupt:
		print("\nCerrando el servidor...", flush=True)
	finally:
		if server.poll() is None:
			server.terminate()
			try:
				server.wait(timeout=10)
			except subprocess.TimeoutExpired:
				server.kill()
				server.wait()


if __name__ == "__main__":
	main()
