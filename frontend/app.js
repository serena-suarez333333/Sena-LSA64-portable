const connectionPill = document.querySelector("#connection-pill");
const connectionLabel = document.querySelector("#connection-label");
const cameraState = document.querySelector("#camera-state");
const cameraStage = document.querySelector("#camera-stage");
const cameraFeed = document.querySelector("#camera-feed");
const processedFeed = document.querySelector("#processed-feed");
const cameraButton = document.querySelector("#toggle-camera");
const cameraButtonLabel = document.querySelector("#camera-button-label");
const cameraHelp = document.querySelector("#camera-help");
const cameraHelpMessage = document.querySelector("#camera-help-message");
const certificateLink = document.querySelector("#certificate-link");
const secureLink = document.querySelector("#secure-link");
const output = document.querySelector("#output");
const gestureDetail = document.querySelector("#gesture-detail");
const handState = document.querySelector("#hand-state");
const stabilityValue = document.querySelector("#stability-value");
const stabilityFill = document.querySelector("#stability-fill");
const transcriptList = document.querySelector("#transcript-list");
const speechToggle = document.querySelector("#speech-toggle");
const footerMessage = document.querySelector("#footer-message");

let socket = null;
let localStream = null;
let frameTimer = null;
let cameraRequestPending = false;
let lastGesture = null;
let stoppedByUser = false;
const frameCanvas = document.createElement("canvas");
const frameContext = frameCanvas.getContext("2d", { alpha: false });

function setConnection(state, label) {
	connectionPill.dataset.state = state;
	connectionLabel.textContent = label;
}

function setCameraButton(isRunning) {
	cameraButtonLabel.textContent = isRunning ? "Pausar cámara" : "Iniciar cámara";
	cameraButton.dataset.running = String(isRunning);
}

function setCameraMessage(message, stateLabel = message) {
	cameraState.textContent = stateLabel;
	footerMessage.textContent = message;
}

function showSecureCameraHelp(message) {
	const host = window.location.hostname || "localhost";
	cameraHelpMessage.textContent = message;
	certificateLink.href = `http://${host}:8000/sena-local-ca.crt`;
	secureLink.href = `https://${host}:8443`;
	cameraHelp.hidden = false;
}

function releaseLocalCamera() {
	if (frameTimer !== null) window.clearTimeout(frameTimer);
	frameTimer = null;
	if (localStream) {
		for (const track of localStream.getTracks()) track.stop();
	}
	localStream = null;
	cameraFeed.pause();
	cameraFeed.srcObject = null;
	cameraStage.classList.remove("has-local-feed", "is-live", "is-processing");
}

function stopCamera() {
	stoppedByUser = true;
	const activeSocket = socket;
	socket = null;
	if (activeSocket && activeSocket.readyState < WebSocket.CLOSING) activeSocket.close();
	releaseLocalCamera();
	setConnection("offline", "En pausa");
	setCameraMessage("Cámara en pausa", "En pausa");
	setCameraButton(false);
}

function speak(text, hint) {
	if (!speechToggle.checked || !("speechSynthesis" in window)) return;
	window.speechSynthesis.cancel();
	const utterance = new SpeechSynthesisUtterance(text);
	utterance.lang = "es-AR";
	utterance.rate = 0.94;
	window.speechSynthesis.speak(utterance);
}

function addTranscriptEntry(text, hint) {
	transcriptList.querySelector(".transcript-empty")?.remove();
	const entry = document.createElement("li");
	entry.className = "transcript-entry";

	const time = document.createElement("time");
	time.dateTime = new Date().toISOString();
	time.textContent = new Intl.DateTimeFormat("es", {
		hour: "2-digit",
		minute: "2-digit",
	}).format(new Date());

	const phrase = document.createElement("span");
	phrase.className = "entry-phrase";
	phrase.textContent = text;

	const description = document.createElement("span");
	description.className = "entry-hint";
	description.textContent = hint || "Gesto reconocido";

	entry.append(time, phrase, description);
	transcriptList.prepend(entry);
	while (transcriptList.children.length > 8) transcriptList.lastElementChild.remove();
	speak(text, hint);
}

function receiveFrame(message) {
	processedFeed.src = `data:image/jpeg;base64,${message.image}`;
	cameraStage.classList.add("is-live", "is-processing");
	setConnection("live", "Cámara activa");
	setCameraMessage("Cámara activa · procesamiento en el equipo servidor", "Cámara activa");
	handState.textContent = message.hands_visible ? "Mano detectada" : "Manos no detectadas";

	if (message.gesture) {
		output.textContent = message.gesture;
		gestureDetail.textContent = message.gesture_hint || "Gesto de demostración";
		const stableFrames = Math.min(message.stable_frames || 0, 4);
		stabilityValue.textContent = `${stableFrames}/4`;
		stabilityFill.style.width = `${(stableFrames / 4) * 100}%`;

		if (message.gesture_id !== lastGesture) {
			addTranscriptEntry(message.gesture, message.gesture_hint);
			lastGesture = message.gesture_id;
		}
	} else {
		output.textContent = "—";
		gestureDetail.textContent = message.hands_visible
			? "Gesto fuera de las reglas de esta demo"
			: "Aún no hay gestos reconocidos";
		stabilityValue.textContent = "—";
		stabilityFill.style.width = "0%";
		lastGesture = null;
	}
}

function sendFrames(activeSocket) {
	if (socket !== activeSocket || !localStream) return;
	if (!document.hidden && cameraFeed.videoWidth && activeSocket.bufferedAmount < 512_000) {
		const width = Math.min(cameraFeed.videoWidth, 640);
		const height = Math.round((cameraFeed.videoHeight * width) / cameraFeed.videoWidth);
		frameCanvas.width = width;
		frameCanvas.height = height;
		frameContext.drawImage(cameraFeed, 0, 0, width, height);
		frameCanvas.toBlob((frame) => {
			if (frame && socket === activeSocket && activeSocket.readyState === WebSocket.OPEN) {
				activeSocket.send(frame);
			}
		}, "image/jpeg", 0.72);
	}
	frameTimer = window.setTimeout(() => sendFrames(activeSocket), 150);
}

function handleCameraError(error) {
	setConnection("error", "Cámara no disponible");
	setCameraButton(false);
	if (error.name === "NotAllowedError" || error.name === "SecurityError") {
		setCameraMessage("El navegador no autorizó la cámara", "Permiso requerido");
		if (!window.isSecureContext) {
			showSecureCameraHelp("La cámara requiere HTTPS. Descarga e instala el certificado local desde esta página HTTP.");
		} else {
			setCameraMessage("Permite el acceso a la cámara en los ajustes del navegador", "Permiso requerido");
		}
	} else if (error.name === "NotFoundError" || error.name === "OverconstrainedError") {
		setCameraMessage("Este dispositivo no encontró una cámara disponible", "Cámara no encontrada");
	} else {
		setCameraMessage("No se pudo iniciar la cámara. Revisa los permisos del navegador.", "Error de cámara");
	}
}

const CAMERA_TIMEOUT_MS = 15000;

function withTimeout(promise, ms) {
	let timer = null;
	const timeout = new Promise((_, reject) => {
		timer = window.setTimeout(() => reject(new Error("camera-timeout")), ms);
	});
	return Promise.race([promise, timeout]).finally(() => window.clearTimeout(timer));
}

async function connectCamera() {
	if (cameraRequestPending || localStream || (socket && socket.readyState < WebSocket.CLOSING)) return;
	cameraRequestPending = true;
	stoppedByUser = false;
	cameraHelp.hidden = true;
	setCameraButton(true);
	cameraButton.disabled = true;
	setConnection("connecting", "Solicitando cámara");
	setCameraMessage("Solicitando permiso para la cámara de este dispositivo…", "Solicitando permiso");

	if (!navigator.mediaDevices?.getUserMedia) {
		cameraRequestPending = false;
		setCameraButton(false);
		cameraButton.disabled = false;
		setConnection("error", "HTTPS requerido");
		setCameraMessage("La cámara requiere una conexión segura", "HTTPS requerido");
		showSecureCameraHelp("Abre esta página por HTTPS para habilitar la cámara del teléfono.");
		return;
	}

	const cameraRequest = navigator.mediaDevices.getUserMedia({
		audio: false,
		video: {
			facingMode: { ideal: "environment" },
			width: { ideal: 640 },
			height: { ideal: 480 },
		},
	});

	try {
		localStream = await withTimeout(cameraRequest, CAMERA_TIMEOUT_MS);
		cameraFeed.srcObject = localStream;
		await cameraFeed.play();
		cameraStage.classList.add("has-local-feed");
	} catch (error) {
		if (error.message === "camera-timeout") {
			// Si el permiso llega más tarde, apaga la cámara que quedó abierta.
			cameraRequest.then((stream) => stream.getTracks().forEach((track) => track.stop())).catch(() => {});
			releaseLocalCamera();
			cameraRequestPending = false;
			cameraButton.disabled = false;
			setCameraButton(false);
			setConnection("error", "Sin respuesta");
			setCameraMessage(
				"El navegador no respondió. Revisa el aviso de permiso de la cámara y que otra app no la esté usando.",
				"Sin respuesta",
			);
			return;
		}
		releaseLocalCamera();
		cameraRequestPending = false;
		cameraButton.disabled = false;
		handleCameraError(error);
		return;
	}

	cameraRequestPending = false;
	cameraButton.disabled = false;
	const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
	const port = window.location.protocol === "https:" ? 8766 : 8765;
	const activeSocket = new WebSocket(`${protocol}//${window.location.hostname || "localhost"}:${port}`);
	socket = activeSocket;

	activeSocket.addEventListener("open", () => {
		if (socket !== activeSocket) return;
		setConnection("connecting", "Preparando detector");
		setCameraMessage("Cámara conectada · preparando detector…", "Preparando detector");
	});

	activeSocket.addEventListener("message", (event) => {
		let message;
		try {
			message = JSON.parse(event.data);
		} catch {
			setCameraMessage("El servidor envió una respuesta no válida");
			return;
		}

		if (message.type === "status" && message.state === "detector_ready") {
			setConnection("live", "Cámara activa");
			setCameraMessage("Cámara activa · procesamiento en el equipo servidor", "Cámara activa");
			sendFrames(activeSocket);
		} else if (message.type === "frame") {
			receiveFrame(message);
		} else if (message.type === "error") {
			stoppedByUser = true;
			setConnection("error", "Cámara no disponible");
			setCameraMessage(message.message, "Error de cámara");
			gestureDetail.textContent = "Esperando señal de cámara";
			setCameraButton(false);
			releaseLocalCamera();
			socket = null;
			activeSocket.close();
		}
	});

	activeSocket.addEventListener("close", () => {
		if (socket !== activeSocket) return;
		socket = null;
		if (!stoppedByUser) {
			releaseLocalCamera();
			setCameraButton(false);
			setConnection("offline", "Desconectado");
			setCameraMessage("No hay conexión con el servidor local", "Sin conexión");
		}
	});

	activeSocket.addEventListener("error", () => {
		if (socket !== activeSocket) return;
		setConnection("error", "Error de conexión");
		setCameraMessage("No se pudo conectar al detector. Revisa el servidor y el certificado.", "Error de conexión");
		stoppedByUser = true;
		releaseLocalCamera();
		setCameraButton(false);
		activeSocket.close();
	});
}

cameraButton.addEventListener("click", () => {
	if (localStream || (socket && socket.readyState < WebSocket.CLOSING)) {
		stopCamera();
	} else {
		connectCamera();
	}
});

document.querySelector("#clear-history").addEventListener("click", () => {
	transcriptList.replaceChildren();
	const empty = document.createElement("li");
	empty.className = "transcript-empty";
	empty.textContent = "Los gestos aparecerán aquí.";
	transcriptList.append(empty);
});

if (!("speechSynthesis" in window)) {
	speechToggle.disabled = true;
	speechToggle.closest(".speech-control").classList.add("is-disabled");
}

setCameraButton(false);
