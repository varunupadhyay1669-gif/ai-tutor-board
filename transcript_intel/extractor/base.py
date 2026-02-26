from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class TrialExtractRequest:
  transcript_text: str
  student_name: str
  grade: Optional[str]
  curriculum: Optional[str]
  target_exam: Optional[str]
  session_date: str


@dataclass(frozen=True)
class TrialExtractResult:
  long_term_goal_summary: str
  goals: list[dict[str, Any]]
  topics: list[dict[str, Any]]
  milestones: list[dict[str, Any]]
  inferred_curriculum_roadmap: dict[str, Any]
  debug: dict[str, Any]


@dataclass(frozen=True)
class SessionExtractRequest:
  transcript_text: str
  session_date: str
  known_topics: list[dict[str, Any]]
  recent_sessions: list[dict[str, Any]]


@dataclass(frozen=True)
class SessionExtractResult:
  extracted_summary: str
  detected_topics: list[str]
  detected_misconceptions: list[str]
  detected_strengths: list[str]
  engagement_score: int
  parent_summary: str
  tutor_insight: str
  recommended_next_targets: list[str]
  per_topic_signals: dict[str, dict[str, Any]]
  per_topic_updates: dict[str, dict[str, Any]]
  mental_block_candidates: list[dict[str, Any]]
  debug: dict[str, Any]


class TranscriptExtractor:
  def extract_trial(self, req: TrialExtractRequest) -> TrialExtractResult:
    raise NotImplementedError

  def extract_session(self, req: SessionExtractRequest) -> SessionExtractResult:
    raise NotImplementedError

