"""MediaPipe Holistic wrapper for camera frames."""

from __future__ import annotations

from typing import Any

try:
	import cv2
	import mediapipe as mp
except ImportError as error:
	cv2 = None
	mp = None
	_IMPORT_ERROR: ImportError | None = error
else:
	_IMPORT_ERROR = None


def _points_for(
	result: Any, include_visibility: bool = False
) -> list[dict[str, float]] | None:
	if result is None:
		return None
	points = []
	for point in result.landmark:
		item = {"x": point.x, "y": point.y, "z": point.z}
		if include_visibility:
			item["visibility"] = point.visibility
		points.append(item)
	return points


class HolisticDetector:
	def __init__(self, static_image_mode: bool = False) -> None:
		if mp is None or cv2 is None:
			raise RuntimeError(
				"Faltan dependencias de visión. Instala backend/requirements.txt."
			) from _IMPORT_ERROR

		self._model = mp.solutions.holistic.Holistic(
			static_image_mode=static_image_mode,
			model_complexity=1,
			smooth_landmarks=True,
			min_detection_confidence=0.55,
			min_tracking_confidence=0.55,
		)

	def _detect(self, frame: Any) -> Any:
		rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
		return self._model.process(rgb_frame)

	def extract_landmarks(self, frame: Any) -> dict[str, Any]:
		"""Extract landmarks without drawing, for offline dataset preparation."""
		results = self._detect(frame)
		return {
			"left_hand": _points_for(results.left_hand_landmarks),
			"right_hand": _points_for(results.right_hand_landmarks),
			"pose": _points_for(results.pose_landmarks, include_visibility=True),
		}

	def process(self, frame: Any) -> tuple[dict[str, Any], Any]:
		results = self._detect(frame)
		annotated = frame.copy()

		for points, connection in (
			(results.pose_landmarks, mp.solutions.holistic.POSE_CONNECTIONS),
			(results.left_hand_landmarks, mp.solutions.hands.HAND_CONNECTIONS),
			(results.right_hand_landmarks, mp.solutions.hands.HAND_CONNECTIONS),
		):
			if points:
				mp.solutions.drawing_utils.draw_landmarks(annotated, points, connection)

		landmarks = {
			"left_hand": _points_for(results.left_hand_landmarks),
			"right_hand": _points_for(results.right_hand_landmarks),
			"pose": _points_for(results.pose_landmarks, include_visibility=True),
		}
		return landmarks, annotated

	def close(self) -> None:
		self._model.close()


def detect_gesture(frame: Any, detector: HolisticDetector) -> tuple[dict[str, Any], Any]:
	"""Detect and draw landmarks for a single BGR camera frame."""
	return detector.process(frame)
