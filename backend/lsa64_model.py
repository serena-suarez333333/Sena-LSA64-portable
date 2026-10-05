"""Sequence features and nearest-neighbor inference for the LSA64 prototype."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np
from numpy.typing import NDArray

FRAME_COUNT = 16
HAND_POINT_COUNT = 21
POSE_LANDMARKS = (0, 11, 12, 13, 14, 15, 16)
HAND_FEATURE_SIZE = HAND_POINT_COUNT * 3 + 3
FRAME_FEATURE_SIZE = HAND_FEATURE_SIZE * 2 + len(POSE_LANDMARKS) * 4
SEQUENCE_FEATURE_SIZE = FRAME_COUNT * FRAME_FEATURE_SIZE

# Spanish labels are indicative translations of the dataset's English glosses.
LSA64_GLOSSES = {
	1: "Opaco", 2: "Rojo", 3: "Verde", 4: "Amarillo", 5: "Brillante",
	6: "Celeste", 7: "Colores", 8: "Rosa", 9: "Mujer", 10: "Enemigo",
	11: "Hijo", 12: "Hombre", 13: "Lejos", 14: "Cajón", 15: "Nacer",
	16: "Aprender", 17: "Llamar", 18: "Espumadera", 19: "Amargo",
	20: "Leche dulce", 21: "Leche", 22: "Agua", 23: "Comida",
	24: "Argentina", 25: "Uruguay", 26: "País", 27: "Apellido",
	28: "Dónde", 29: "Burlarse", 30: "Cumpleaños", 31: "Desayuno",
	32: "Foto", 33: "Hambre", 34: "Mapa", 35: "Moneda", 36: "Música",
	37: "Barco", 38: "Ninguno", 39: "Nombre", 40: "Paciencia",
	41: "Perfume", 42: "Sordo", 43: "Trampa", 44: "Arroz",
	45: "Asado", 46: "Caramelo", 47: "Chicle", 48: "Espaguetis",
	49: "Yogur", 50: "Aceptar", 51: "Gracias", 52: "Apagar",
	53: "Aparecer", 54: "Aterrizar", 55: "Atrapar", 56: "Ayudar",
	57: "Bailar", 58: "Bañarse", 59: "Comprar", 60: "Copiar",
	61: "Correr", 62: "Darse cuenta", 63: "Dar", 64: "Encontrar",
}

FrameFeatures = NDArray[np.float32]
SequenceFeatures = NDArray[np.float32]


def _hand_features(points: Any) -> list[float]:
	if not points or len(points) < HAND_POINT_COUNT:
		return [0.0] * HAND_FEATURE_SIZE

	coordinates = np.asarray(
		[[point["x"], point["y"], point.get("z", 0.0)] for point in points[:HAND_POINT_COUNT]],
		dtype=np.float32,
	)
	origin = coordinates[0]
	scale = float(np.linalg.norm(coordinates[:, :2] - origin[:2], axis=1).max())
	if scale == 0.0:
		scale = 1.0
	relative = (coordinates - origin) / scale
	return [*relative.flatten().tolist(), *origin.tolist()]


def frame_features(landmarks: dict[str, Any] | None) -> FrameFeatures:
	"""Convert one Holistic result to a stable, normalized feature vector."""
	if not landmarks:
		landmarks = {}

	values = _hand_features(landmarks.get("left_hand"))
	values.extend(_hand_features(landmarks.get("right_hand")))
	pose = landmarks.get("pose")
	for index in POSE_LANDMARKS:
		if pose and len(pose) > index:
			point = pose[index]
			values.extend(
				[
					float(point["x"]),
					float(point["y"]),
					float(point.get("z", 0.0)),
					float(point.get("visibility", 0.0)),
				]
			)
		else:
			values.extend([0.0] * 4)
	return np.asarray(values, dtype=np.float32)


def sequence_features(frames: Sequence[FrameFeatures]) -> SequenceFeatures:
	"""Flatten a sequence of exactly FRAME_COUNT frame feature vectors."""
	sequence = np.asarray(frames, dtype=np.float32)
	expected_shape = (FRAME_COUNT, FRAME_FEATURE_SIZE)
	if sequence.shape != expected_shape:
		raise ValueError(
			f"La secuencia debe tener forma {expected_shape}; se recibió {sequence.shape}."
		)
	return sequence.reshape(SEQUENCE_FEATURE_SIZE)


class LSA64Classifier:
	"""Nearest-neighbor classifier over locally trained LSA64 video sequences."""

	def __init__(
		self,
		templates: NDArray[np.float32],
		labels: NDArray[np.str_],
		max_distance: float,
	) -> None:
		if templates.ndim != 2 or templates.shape[1] != SEQUENCE_FEATURE_SIZE:
			raise ValueError("El archivo del modelo tiene una forma de características inválida.")
		if labels.ndim != 1 or len(labels) != len(templates) or len(labels) == 0:
			raise ValueError("El archivo del modelo tiene etiquetas inválidas.")
		if not np.isfinite(max_distance) or max_distance <= 0:
			raise ValueError("El archivo del modelo tiene un umbral de distancia inválido.")
		self._templates = templates.astype(np.float32, copy=False)
		self._labels = labels
		self._max_distance = float(max_distance)

	@classmethod
	def load(cls, path: Path) -> LSA64Classifier:
		with np.load(path, allow_pickle=False) as model:
			return cls(model["features"], model["labels"], float(model["max_distance"]))

	def classify(self, frames: Sequence[FrameFeatures]) -> str | None:
		vector = sequence_features(frames)
		differences = self._templates - vector
		distances = np.mean(differences * differences, axis=1)
		best_index = int(np.argmin(distances))
		if distances[best_index] > self._max_distance:
			return None
		return f"lsa64_{self._labels[best_index]}"

	def label(self, gesture_id: str) -> tuple[str, str]:
		class_id = int(gesture_id.rsplit("_", maxsplit=1)[-1])
		gloss = LSA64_GLOSSES.get(class_id, f"Seña {class_id:02d}")
		return gloss, f"LSA64 #{class_id:02d} · etiqueta orientativa"


def save_templates(path: Path, features: Sequence[SequenceFeatures], labels: Sequence[str]) -> None:
	if not features:
		raise ValueError("No se extrajeron secuencias válidas de LSA64.")
	if len(features) != len(labels):
		raise ValueError("Cada secuencia debe tener exactamente una etiqueta.")
	template_array = np.asarray(features, dtype=np.float32)
	label_array = np.asarray(labels, dtype=np.str_)
	nearest_same_class = []
	for index, label in enumerate(label_array):
		matches = np.flatnonzero(label_array == label)
		matches = matches[matches != index]
		if len(matches) == 0:
			continue
		differences = template_array[matches] - template_array[index]
		nearest_same_class.append(float(np.mean(differences * differences, axis=1).min()))
	if not nearest_same_class:
		raise ValueError("Se necesitan al menos dos videos por clase para calibrar el umbral.")
	max_distance = float(np.percentile(nearest_same_class, 95))
	if max_distance <= 0:
		max_distance = float(np.finfo(np.float32).eps)
	path.parent.mkdir(parents=True, exist_ok=True)
	np.savez_compressed(
		path,
		features=template_array,
		labels=label_array,
		max_distance=np.asarray(max_distance, dtype=np.float32),
	)
