from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional


def now_iso() -> str:
  return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_dir(path: str) -> None:
  os.makedirs(path, exist_ok=True)


def open_db(db_path: str) -> sqlite3.Connection:
  ensure_dir(os.path.dirname(db_path))
  conn = sqlite3.connect(db_path)
  conn.row_factory = sqlite3.Row
  conn.execute("PRAGMA foreign_keys = ON;")
  ensure_schema(conn)
  return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
  here = os.path.dirname(__file__)
  schema_path = os.path.join(here, "schema.sql")
  with open(schema_path, "r", encoding="utf-8") as f:
    conn.executescript(f.read())
  conn.commit()


def _json_dumps(value: Any) -> str:
  return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(raw: Optional[str], default: Any) -> Any:
  if raw is None or raw == "":
    return default
  try:
    return json.loads(raw)
  except json.JSONDecodeError:
    return default


@dataclass(frozen=True)
class StudentRow:
  id: int
  name: str
  grade: Optional[str]
  curriculum: Optional[str]
  target_exam: Optional[str]
  long_term_goal_summary: Optional[str]


def create_student(
  conn: sqlite3.Connection,
  *,
  name: str,
  grade: Optional[str] = None,
  curriculum: Optional[str] = None,
  target_exam: Optional[str] = None,
  long_term_goal_summary: Optional[str] = None,
) -> int:
  cur = conn.execute(
    """
    INSERT INTO student (name, grade, curriculum, target_exam, long_term_goal_summary)
    VALUES (?, ?, ?, ?, ?)
    """,
    (name, grade, curriculum, target_exam, long_term_goal_summary),
  )
  conn.commit()
  return int(cur.lastrowid)


def update_student_goal_summary(conn: sqlite3.Connection, *, student_id: int, summary: str) -> None:
  conn.execute("UPDATE student SET long_term_goal_summary = ? WHERE id = ?", (summary, student_id))
  conn.commit()


def list_students(conn: sqlite3.Connection) -> list[StudentRow]:
  rows = conn.execute(
    "SELECT id, name, grade, curriculum, target_exam, long_term_goal_summary FROM student ORDER BY created_at DESC"
  ).fetchall()
  return [
    StudentRow(
      id=int(r["id"]),
      name=str(r["name"]),
      grade=r["grade"],
      curriculum=r["curriculum"],
      target_exam=r["target_exam"],
      long_term_goal_summary=r["long_term_goal_summary"],
    )
    for r in rows
  ]


def get_student(conn: sqlite3.Connection, *, student_id: int) -> Optional[StudentRow]:
  r = conn.execute(
    "SELECT id, name, grade, curriculum, target_exam, long_term_goal_summary FROM student WHERE id = ?",
    (student_id,),
  ).fetchone()
  if not r:
    return None
  return StudentRow(
    id=int(r["id"]),
    name=str(r["name"]),
    grade=r["grade"],
    curriculum=r["curriculum"],
    target_exam=r["target_exam"],
    long_term_goal_summary=r["long_term_goal_summary"],
  )


def add_goals(conn: sqlite3.Connection, *, student_id: int, goals: Iterable[dict[str, Any]]) -> list[int]:
  ids: list[int] = []
  for g in goals:
    cur = conn.execute(
      """
      INSERT INTO goal (student_id, description, measurable_outcome, deadline, status)
      VALUES (?, ?, ?, ?, ?)
      """,
      (
        student_id,
        str(g.get("description", "")).strip(),
        (str(g["measurable_outcome"]).strip() if g.get("measurable_outcome") else None),
        (str(g["deadline"]).strip() if g.get("deadline") else None),
        str(g.get("status") or "not started"),
      ),
    )
    ids.append(int(cur.lastrowid))
  conn.commit()
  return ids


def list_goals(conn: sqlite3.Connection, *, student_id: int) -> list[dict[str, Any]]:
  rows = conn.execute(
    """
    SELECT id, description, measurable_outcome, deadline, status
    FROM goal
    WHERE student_id = ?
    ORDER BY
      CASE status
        WHEN 'achieved' THEN 2
        WHEN 'in progress' THEN 1
        ELSE 0
      END ASC,
      COALESCE(deadline, '') ASC,
      id ASC
    """,
    (student_id,),
  ).fetchall()
  return [
    {
      "id": int(r["id"]),
      "description": str(r["description"]),
      "measurable_outcome": r["measurable_outcome"],
      "deadline": r["deadline"],
      "status": str(r["status"]),
    }
    for r in rows
  ]


def upsert_topic(
  conn: sqlite3.Connection,
  *,
  student_id: int,
  topic_name: str,
  parent_topic: Optional[str] = None,
  mastery_score: Optional[int] = None,
  confidence_score: Optional[int] = None,
) -> None:
  existing = conn.execute(
    "SELECT mastery_score, confidence_score, parent_topic FROM topic WHERE student_id = ? AND topic_name = ?",
    (student_id, topic_name),
  ).fetchone()
  if existing:
    new_parent = parent_topic if parent_topic is not None else existing["parent_topic"]
    new_mastery = int(mastery_score) if mastery_score is not None else int(existing["mastery_score"])
    new_conf = int(confidence_score) if confidence_score is not None else int(existing["confidence_score"])
    conn.execute(
      """
      UPDATE topic
      SET parent_topic = ?, mastery_score = ?, confidence_score = ?
      WHERE student_id = ? AND topic_name = ?
      """,
      (new_parent, new_mastery, new_conf, student_id, topic_name),
    )
  else:
    conn.execute(
      """
      INSERT INTO topic (student_id, topic_name, parent_topic, mastery_score, confidence_score)
      VALUES (?, ?, ?, ?, ?)
      """,
      (
        student_id,
        topic_name,
        parent_topic,
        int(mastery_score) if mastery_score is not None else 0,
        int(confidence_score) if confidence_score is not None else 0,
      ),
    )
  conn.commit()


def list_topics(conn: sqlite3.Connection, *, student_id: int) -> list[dict[str, Any]]:
  rows = conn.execute(
    """
    SELECT id, topic_name, parent_topic, mastery_score, confidence_score
    FROM topic
    WHERE student_id = ?
    ORDER BY COALESCE(parent_topic, topic_name), topic_name
    """,
    (student_id,),
  ).fetchall()
  return [
    {
      "id": int(r["id"]),
      "topic_name": str(r["topic_name"]),
      "parent_topic": r["parent_topic"],
      "mastery_score": int(r["mastery_score"]),
      "confidence_score": int(r["confidence_score"]),
    }
    for r in rows
  ]


def add_session(
  conn: sqlite3.Connection,
  *,
  student_id: int,
  transcript_text: str,
  session_date: str,
  extracted_summary: Optional[str],
  detected_topics: list[str],
  detected_misconceptions: list[str],
  detected_strengths: list[str],
  engagement_score: Optional[int],
  parent_summary: Optional[str],
  tutor_insight: Optional[str],
  recommended_next_targets: list[str],
) -> int:
  cur = conn.execute(
    """
    INSERT INTO session (
      student_id, transcript_text, session_date, extracted_summary,
      detected_topics, detected_misconceptions, detected_strengths,
      engagement_score, parent_summary, tutor_insight, recommended_next_targets
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
      student_id,
      transcript_text,
      session_date,
      extracted_summary,
      _json_dumps(detected_topics),
      _json_dumps(detected_misconceptions),
      _json_dumps(detected_strengths),
      int(engagement_score) if engagement_score is not None else None,
      parent_summary,
      tutor_insight,
      _json_dumps(recommended_next_targets),
    ),
  )
  conn.commit()
  return int(cur.lastrowid)


def list_sessions(conn: sqlite3.Connection, *, student_id: int, limit: int = 50) -> list[dict[str, Any]]:
  rows = conn.execute(
    """
    SELECT id, session_date, extracted_summary, detected_topics, detected_misconceptions,
           detected_strengths, engagement_score, parent_summary, tutor_insight, recommended_next_targets
    FROM session
    WHERE student_id = ?
    ORDER BY session_date DESC, id DESC
    LIMIT ?
    """,
    (student_id, int(limit)),
  ).fetchall()
  out: list[dict[str, Any]] = []
  for r in rows:
    out.append(
      {
        "id": int(r["id"]),
        "session_date": str(r["session_date"]),
        "extracted_summary": r["extracted_summary"],
        "detected_topics": _json_loads(r["detected_topics"], []),
        "detected_misconceptions": _json_loads(r["detected_misconceptions"], []),
        "detected_strengths": _json_loads(r["detected_strengths"], []),
        "engagement_score": r["engagement_score"],
        "parent_summary": r["parent_summary"],
        "tutor_insight": r["tutor_insight"],
        "recommended_next_targets": _json_loads(r["recommended_next_targets"], []),
      }
    )
  return out


def record_topic_event(
  conn: sqlite3.Connection,
  *,
  student_id: int,
  topic_name: str,
  session_id: Optional[int],
  event_date: str,
  previous_mastery: int,
  new_mastery: int,
  previous_confidence: int,
  new_confidence: int,
  explanation: dict[str, Any],
) -> None:
  conn.execute(
    """
    INSERT INTO topic_mastery_event (
      student_id, topic_name, session_id, event_date,
      previous_mastery, new_mastery, previous_confidence, new_confidence, explanation_json
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
      student_id,
      topic_name,
      session_id,
      event_date,
      int(previous_mastery),
      int(new_mastery),
      int(previous_confidence),
      int(new_confidence),
      _json_dumps(explanation),
    ),
  )
  conn.commit()


def list_topic_events(conn: sqlite3.Connection, *, student_id: int, topic_name: Optional[str] = None) -> list[dict[str, Any]]:
  if topic_name:
    rows = conn.execute(
      """
      SELECT id, topic_name, session_id, event_date, previous_mastery, new_mastery, previous_confidence, new_confidence, explanation_json
      FROM topic_mastery_event
      WHERE student_id = ? AND topic_name = ?
      ORDER BY event_date ASC, id ASC
      """,
      (student_id, topic_name),
    ).fetchall()
  else:
    rows = conn.execute(
      """
      SELECT id, topic_name, session_id, event_date, previous_mastery, new_mastery, previous_confidence, new_confidence, explanation_json
      FROM topic_mastery_event
      WHERE student_id = ?
      ORDER BY event_date ASC, id ASC
      """,
      (student_id,),
    ).fetchall()

  return [
    {
      "id": int(r["id"]),
      "topic_name": str(r["topic_name"]),
      "session_id": r["session_id"],
      "event_date": str(r["event_date"]),
      "previous_mastery": int(r["previous_mastery"]),
      "new_mastery": int(r["new_mastery"]),
      "previous_confidence": int(r["previous_confidence"]),
      "new_confidence": int(r["new_confidence"]),
      "explanation": _json_loads(r["explanation_json"], {}),
    }
    for r in rows
  ]


def upsert_mental_block(
  conn: sqlite3.Connection,
  *,
  student_id: int,
  description: str,
  detected_at: str,
  initial_severity: int,
  repeat_severity_delta: int,
) -> dict[str, Any]:
  existing = conn.execute(
    """
    SELECT id, first_detected, last_detected, frequency_count, severity_score
    FROM mental_block
    WHERE student_id = ? AND description = ?
    """,
    (student_id, description),
  ).fetchone()
  if existing:
    new_freq = int(existing["frequency_count"]) + 1
    new_sev = min(100, max(0, int(existing["severity_score"]) + int(repeat_severity_delta)))
    conn.execute(
      """
      UPDATE mental_block
      SET last_detected = ?, frequency_count = ?, severity_score = ?
      WHERE id = ?
      """,
      (detected_at, new_freq, new_sev, int(existing["id"])),
    )
    conn.commit()
    return {
      "id": int(existing["id"]),
      "description": description,
      "first_detected": str(existing["first_detected"]),
      "last_detected": detected_at,
      "frequency_count": new_freq,
      "severity_score": new_sev,
    }
  else:
    cur = conn.execute(
      """
      INSERT INTO mental_block (student_id, description, first_detected, last_detected, frequency_count, severity_score)
      VALUES (?, ?, ?, ?, 1, ?)
      """,
      (student_id, description, detected_at, detected_at, min(100, max(0, int(initial_severity)))),
    )
    conn.commit()
    return {
      "id": int(cur.lastrowid),
      "description": description,
      "first_detected": detected_at,
      "last_detected": detected_at,
      "frequency_count": 1,
      "severity_score": min(100, max(0, int(initial_severity))),
    }


def list_mental_blocks(conn: sqlite3.Connection, *, student_id: int) -> list[dict[str, Any]]:
  rows = conn.execute(
    """
    SELECT id, description, first_detected, last_detected, frequency_count, severity_score
    FROM mental_block
    WHERE student_id = ?
    ORDER BY severity_score DESC, frequency_count DESC, last_detected DESC
    """,
    (student_id,),
  ).fetchall()
  return [
    {
      "id": int(r["id"]),
      "description": str(r["description"]),
      "first_detected": str(r["first_detected"]),
      "last_detected": str(r["last_detected"]),
      "frequency_count": int(r["frequency_count"]),
      "severity_score": int(r["severity_score"]),
    }
    for r in rows
  ]
