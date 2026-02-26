from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def clamp_int(value: int, lo: int, hi: int) -> int:
  return max(lo, min(hi, int(value)))


def clamp_float(value: float, lo: float, hi: float) -> float:
  return max(lo, min(hi, float(value)))


@dataclass(frozen=True)
class GrowthConfig:
  improvement_weight: float = 1.0
  error_penalty: float = 2.5
  repeated_error_penalty: float = 4.0
  independent_bonus: float = 2.0

  confidence_positive_weight: float = 4.0
  confidence_negative_weight: float = 6.0

  max_session_delta: int = 12
  min_session_delta: int = -12

  mental_block_session_threshold: int = 3
  mental_block_base_severity: int = 35
  mental_block_repeat_delta: int = 15
  mental_block_avoidance_bonus: int = 15


def update_mastery_and_confidence(
  *,
  previous_mastery: int,
  previous_confidence: int,
  signals: dict[str, Any],
  config: GrowthConfig,
) -> tuple[int, int, dict[str, Any]]:
  attempt_count = int(signals.get("attempt_count") or 0)
  error_count = int(signals.get("error_count") or 0)
  repeated_error_count = int(signals.get("repeated_error_count") or 0)
  independent_count = int(signals.get("independent_count") or 0)
  hint_count = int(signals.get("hint_count") or 0)
  confidence_pos = int(signals.get("confidence_positive") or 0)
  confidence_neg = int(signals.get("confidence_negative") or 0)

  denom_errors = max(1, error_count)
  correction_speed = 1.0 / (1.0 + (hint_count / float(denom_errors)))
  denom_attempts = max(1, attempt_count)
  independence = independent_count / float(denom_attempts)

  improvement_factor = 10.0 * config.improvement_weight * correction_speed * independence
  repeated_error_penalty = config.repeated_error_penalty * float(repeated_error_count)
  error_penalty = config.error_penalty * float(error_count)
  independent_bonus = config.independent_bonus * float(independent_count)

  raw_delta = improvement_factor + independent_bonus - error_penalty - repeated_error_penalty
  bounded_delta = clamp_float(raw_delta, float(config.min_session_delta), float(config.max_session_delta))
  mastery_delta = int(round(bounded_delta))
  new_mastery = clamp_int(previous_mastery + mastery_delta, 0, 100)

  raw_conf_delta = (confidence_pos * config.confidence_positive_weight) - (confidence_neg * config.confidence_negative_weight)
  raw_conf_delta += 6.0 * independence
  raw_conf_delta -= 2.0 * float(error_count)
  conf_delta = int(round(clamp_float(raw_conf_delta, -12.0, 12.0)))
  new_confidence = clamp_int(previous_confidence + conf_delta, 0, 100)

  explanation = {
    "formula": "new = clamp(prev + round(delta), 0, 100)",
    "delta_components": {
      "improvement_factor": improvement_factor,
      "independent_bonus": independent_bonus,
      "error_penalty": error_penalty,
      "repeated_error_penalty": repeated_error_penalty,
    },
    "derived_signals": {
      "correction_speed": correction_speed,
      "independence": independence,
    },
    "bounded_delta": bounded_delta,
    "mastery_delta": mastery_delta,
    "confidence_delta": conf_delta,
    "signals_used": {
      "attempt_count": attempt_count,
      "error_count": error_count,
      "repeated_error_count": repeated_error_count,
      "independent_count": independent_count,
      "hint_count": hint_count,
      "confidence_positive": confidence_pos,
      "confidence_negative": confidence_neg,
    },
  }

  return new_mastery, new_confidence, explanation

