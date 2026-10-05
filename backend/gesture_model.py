"""Small, explicitly heuristic gesture classifier for the live demo."""

from __future__ import annotations

from math import hypot
from typing import Any


def _distance(first: dict[str, float], second: dict[str, float]) -> float:
	return hypot(first["x"] - second["x"], first["y"] - second["y"])


def _finger_is_extended(hand: list[dict[str, float]], tip: int, pip: int) -> bool:
	return hand[tip]["y"] < hand[pip]["y"] - 0.025


def classify(landmarks: dict[str, Any] | None) -> str | None:
	"""Return a demo gesture ID from one hand's normalized landmarks."""
	if not landmarks:
		return None

	hand = landmarks.get("right_hand") or landmarks.get("left_hand")
	if not hand or len(hand) < 21:
		return None

	extended = [
		_finger_is_extended(hand, tip, pip)
		for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18))
	]
	thumb_extended = _distance(hand[4], hand[9]) > _distance(hand[3], hand[9]) * 1.12
	count = sum(extended)

	if count == 4 and thumb_extended:
		return "open_palm"
	if count == 0 and not thumb_extended:
		return "fist"
	if count == 0 and thumb_extended:
		return "thumbs_up"
	return None
