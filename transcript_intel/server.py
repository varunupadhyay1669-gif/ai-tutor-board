from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from .db import (
  add_goals,
  add_session,
  create_student,
  get_student,
  list_goals,
  list_mental_blocks,
  list_sessions,
  list_students,
  list_topic_events,
  list_topics,
  open_db,
  record_topic_event,
  update_student_goal_summary,
  upsert_mental_block,
  upsert_topic,
)
from .extractor.base import SessionExtractRequest, TrialExtractRequest
from .extractor.heuristic import HeuristicTranscriptExtractor, TOPIC_TAXONOMY
from .growth import GrowthConfig


def _json_bytes(data: Any) -> bytes:
  return (json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _guess_content_type(path: str) -> str:
  if path.endswith(".html"):
    return "text/html; charset=utf-8"
  if path.endswith(".css"):
    return "text/css; charset=utf-8"
  if path.endswith(".js"):
    return "application/javascript; charset=utf-8"
  if path.endswith(".json"):
    return "application/json; charset=utf-8"
  if path.endswith(".svg"):
    return "image/svg+xml"
  if path.endswith(".png"):
    return "image/png"
  if path.endswith(".jpg") or path.endswith(".jpeg"):
    return "image/jpeg"
  return "application/octet-stream"


def _safe_join(root: str, url_path: str) -> Optional[str]:
  # Prevent path traversal.
  path = url_path.split("?", 1)[0].split("#", 1)[0]
  path = posixpath.normpath(path)
  path = path.lstrip("/")
  if path.startswith(".."):
    return None
  return os.path.join(root, *path.split("/"))


def _topic_parent_lookup(topic_name: str) -> Optional[str]:
  for parent, children in TOPIC_TAXONOMY.items():
    if topic_name in children:
      return parent
  return None


class App:
  def __init__(self, *, db_path: str):
    self.conn = open_db(db_path)
    self.extractor = HeuristicTranscriptExtractor(config=GrowthConfig())


class Handler(BaseHTTPRequestHandler):
  server_version = "TranscriptIntel/0.1"

  def _send_json(self, status: int, data: Any) -> None:
    body = _json_bytes(data)
    self.send_response(status)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Cache-Control", "no-store")
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Headers", "Content-Type")
    self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    self.end_headers()
    self.wfile.write(body)

  def _read_json(self) -> Any:
    length = int(self.headers.get("Content-Length") or "0")
    raw = self.rfile.read(length) if length > 0 else b""
    try:
      return json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
      return None

  @property
  def app(self) -> App:
    return self.server.app  # type: ignore[attr-defined]

  @property
  def static_root(self) -> str:
    return self.server.static_root  # type: ignore[attr-defined]

  def do_OPTIONS(self) -> None:
    self.send_response(HTTPStatus.NO_CONTENT)
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Headers", "Content-Type")
    self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    self.end_headers()

  def do_GET(self) -> None:
    parsed = urlparse(self.path)
    path = parsed.path or "/"

    if path.startswith("/api/"):
      self._handle_api_get(parsed)
      return

    if path == "/":
      path = "/index.html"

    abs_path = _safe_join(self.static_root, path)
    if not abs_path or not os.path.isfile(abs_path):
      self.send_error(HTTPStatus.NOT_FOUND, "Not found")
      return

    try:
      with open(abs_path, "rb") as f:
        data = f.read()
    except OSError:
      self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to read file")
      return

    self.send_response(HTTPStatus.OK)
    self.send_header("Content-Type", _guess_content_type(abs_path))
    self.send_header("Content-Length", str(len(data)))
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    self.wfile.write(data)

  def do_POST(self) -> None:
    parsed = urlparse(self.path)
    path = parsed.path or "/"
    if not path.startswith("/api/"):
      self.send_error(HTTPStatus.NOT_FOUND, "Not found")
      return
    self._handle_api_post(parsed)

  def _handle_api_get(self, parsed) -> None:
    path = parsed.path or ""

    if path == "/api/health":
      self._send_json(HTTPStatus.OK, {"ok": True})
      return

    if path == "/api/config":
      self._send_json(
        HTTPStatus.OK,
        {
          "mastery_update_formula": "new_mastery = clamp(prev_mastery + round(delta), 0, 100)",
          "delta": "delta = improvement_factor + independent_bonus - error_penalty - repeated_error_penalty (bounded per session)",
          "growth_config": self.app.extractor.config.__dict__,
        },
      )
      return

    if path == "/api/students":
      students = [s.__dict__ for s in list_students(self.app.conn)]
      self._send_json(HTTPStatus.OK, {"students": students})
      return

    m = re.match(r"^/api/students/(\d+)/dashboard$", path)
    if m:
      student_id = int(m.group(1))
      student = get_student(self.app.conn, student_id=student_id)
      if not student:
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "student_not_found"})
        return
      view = (parse_qs(parsed.query).get("view") or ["tutor"])[0]
      payload = {
        "student": student.__dict__,
        "view": view,
        "goals": list_goals(self.app.conn, student_id=student_id),
        "topics": list_topics(self.app.conn, student_id=student_id),
        "sessions": list_sessions(self.app.conn, student_id=student_id, limit=50),
        "mental_blocks": list_mental_blocks(self.app.conn, student_id=student_id),
        "topic_events": list_topic_events(self.app.conn, student_id=student_id),
      }
      self._send_json(HTTPStatus.OK, payload)
      return

    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

  def _handle_api_post(self, parsed) -> None:
    path = parsed.path or ""
    body = self._read_json()
    if body is None:
      self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
      return

    if path == "/api/students":
      name = str(body.get("name") or "").strip()
      if not name:
        self._send_json(HTTPStatus.BAD_REQUEST, {"error": "missing_name"})
        return
      student_id = create_student(
        self.app.conn,
        name=name,
        grade=(str(body.get("grade")).strip() if body.get("grade") is not None else None),
        curriculum=(str(body.get("curriculum")).strip() if body.get("curriculum") is not None else None),
        target_exam=(str(body.get("target_exam")).strip() if body.get("target_exam") is not None else None),
      )
      self._send_json(HTTPStatus.OK, {"student_id": student_id})
      return

    if path == "/api/trial":
      student = body.get("student") or {}
      transcript_text = str(body.get("transcript_text") or "").strip()
      session_date = str(body.get("session_date") or "").strip()
      if not transcript_text:
        self._send_json(HTTPStatus.BAD_REQUEST, {"error": "missing_transcript_text"})
        return
      if not session_date:
        self._send_json(HTTPStatus.BAD_REQUEST, {"error": "missing_session_date"})
        return
      name = str(student.get("name") or "").strip()
      if not name:
        self._send_json(HTTPStatus.BAD_REQUEST, {"error": "missing_student_name"})
        return

      req = TrialExtractRequest(
        transcript_text=transcript_text,
        student_name=name,
        grade=(str(student.get("grade")).strip() if student.get("grade") is not None else None),
        curriculum=(str(student.get("curriculum")).strip() if student.get("curriculum") is not None else None),
        target_exam=(str(student.get("target_exam")).strip() if student.get("target_exam") is not None else None),
        session_date=session_date,
      )
      extracted = self.app.extractor.extract_trial(req)

      student_id = create_student(
        self.app.conn,
        name=name,
        grade=req.grade,
        curriculum=req.curriculum,
        target_exam=req.target_exam,
        long_term_goal_summary=extracted.long_term_goal_summary,
      )
      add_goals(self.app.conn, student_id=student_id, goals=extracted.goals)

      for t in extracted.topics:
        upsert_topic(
          self.app.conn,
          student_id=student_id,
          topic_name=str(t["topic_name"]),
          parent_topic=(str(t.get("parent_topic")).strip() if t.get("parent_topic") else None),
          mastery_score=int(t.get("mastery_score") or 0),
          confidence_score=int(t.get("confidence_score") or 0),
        )

      # Store the trial as a session for the timeline.
      add_session(
        self.app.conn,
        student_id=student_id,
        transcript_text=transcript_text,
        session_date=session_date,
        extracted_summary="Trial intake: goals + roadmap captured.",
        detected_topics=[t["topic_name"] for t in extracted.topics[:8]],
        detected_misconceptions=[],
        detected_strengths=[],
        engagement_score=None,
        parent_summary="Trial session completed. Goals and roadmap are set.",
        tutor_insight="Trial transcript processed into goals + topic map.",
        recommended_next_targets=[t["topic_name"] for t in extracted.topics[:3]],
      )

      self._send_json(
        HTTPStatus.OK,
        {
          "student_id": student_id,
          "trial_extraction": {
            "long_term_goal_summary": extracted.long_term_goal_summary,
            "goals": extracted.goals,
            "topics": extracted.topics,
            "milestones": extracted.milestones,
            "inferred_curriculum_roadmap": extracted.inferred_curriculum_roadmap,
          },
        },
      )
      return

    if path == "/api/session":
      student_id = body.get("student_id")
      transcript_text = str(body.get("transcript_text") or "").strip()
      session_date = str(body.get("session_date") or "").strip()
      if not isinstance(student_id, int):
        try:
          student_id = int(student_id)
        except Exception:
          student_id = None
      if not student_id:
        self._send_json(HTTPStatus.BAD_REQUEST, {"error": "missing_student_id"})
        return
      if not transcript_text:
        self._send_json(HTTPStatus.BAD_REQUEST, {"error": "missing_transcript_text"})
        return
      if not session_date:
        self._send_json(HTTPStatus.BAD_REQUEST, {"error": "missing_session_date"})
        return

      student = get_student(self.app.conn, student_id=student_id)
      if not student:
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "student_not_found"})
        return

      known_topics = list_topics(self.app.conn, student_id=student_id)
      recent_sessions = list_sessions(self.app.conn, student_id=student_id, limit=25)

      extracted = self.app.extractor.extract_session(
        SessionExtractRequest(
          transcript_text=transcript_text,
          session_date=session_date,
          known_topics=known_topics,
          recent_sessions=recent_sessions,
        )
      )

      session_id = add_session(
        self.app.conn,
        student_id=student_id,
        transcript_text=transcript_text,
        session_date=session_date,
        extracted_summary=extracted.extracted_summary,
        detected_topics=extracted.detected_topics,
        detected_misconceptions=extracted.detected_misconceptions,
        detected_strengths=extracted.detected_strengths,
        engagement_score=extracted.engagement_score,
        parent_summary=extracted.parent_summary,
        tutor_insight=extracted.tutor_insight,
        recommended_next_targets=extracted.recommended_next_targets,
      )

      # Apply topic updates and record events.
      known_by_name = {str(t["topic_name"]): t for t in known_topics}
      for topic_name, upd in extracted.per_topic_updates.items():
        parent = known_by_name.get(topic_name, {}).get("parent_topic") or _topic_parent_lookup(topic_name)
        upsert_topic(
          self.app.conn,
          student_id=student_id,
          topic_name=topic_name,
          parent_topic=parent,
          mastery_score=int(upd["new_mastery"]),
          confidence_score=int(upd["new_confidence"]),
        )
        record_topic_event(
          self.app.conn,
          student_id=student_id,
          topic_name=topic_name,
          session_id=session_id,
          event_date=session_date,
          previous_mastery=int(upd["previous_mastery"]),
          new_mastery=int(upd["new_mastery"]),
          previous_confidence=int(upd["previous_confidence"]),
          new_confidence=int(upd["new_confidence"]),
          explanation=dict(upd["explanation"]),
        )

      # Mental blocks.
      mental_blocks_applied = []
      for cand in extracted.mental_block_candidates:
        mb = upsert_mental_block(
          self.app.conn,
          student_id=student_id,
          description=str(cand["description"]),
          detected_at=session_date,
          initial_severity=int(cand["initial_severity"]),
          repeat_severity_delta=int(cand["repeat_severity_delta"]),
        )
        mental_blocks_applied.append(mb)

      # Keep the student's long-term summary current if it's missing.
      if not (student.long_term_goal_summary or "").strip():
        update_student_goal_summary(self.app.conn, student_id=student_id, summary="Ongoing goals tracked via dashboard.")

      self._send_json(
        HTTPStatus.OK,
        {
          "student_id": student_id,
          "session_id": session_id,
          "session_extraction": {
            "extracted_summary": extracted.extracted_summary,
            "detected_topics": extracted.detected_topics,
            "detected_misconceptions": extracted.detected_misconceptions,
            "detected_strengths": extracted.detected_strengths,
            "engagement_score": extracted.engagement_score,
            "parent_summary": extracted.parent_summary,
            "tutor_insight": extracted.tutor_insight,
            "recommended_next_targets": extracted.recommended_next_targets,
            "per_topic_updates": extracted.per_topic_updates,
            "mental_blocks_applied": mental_blocks_applied,
          },
        },
      )
      return

    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})


class Server(HTTPServer):
  def __init__(self, server_address, RequestHandlerClass, *, app: App, static_root: str):
    super().__init__(server_address, RequestHandlerClass)
    self.app = app
    self.static_root = static_root


def main(argv: Optional[list[str]] = None) -> int:
  parser = argparse.ArgumentParser(description="Transcript Intelligence Dashboard (local server)")
  parser.add_argument("--host", default="127.0.0.1")
  parser.add_argument("--port", type=int, default=5179)
  parser.add_argument("--db", default=os.environ.get("TRANSCRIPT_INTEL_DB") or "")
  args = parser.parse_args(argv)

  here = os.path.dirname(__file__)
  static_root = os.path.join(here, "static")
  db_path = args.db or os.path.join(here, "data", "dashboard.sqlite3")

  app = App(db_path=db_path)
  httpd = Server((args.host, args.port), Handler, app=app, static_root=static_root)
  print(f"Serving Transcript Intelligence Dashboard on http://{args.host}:{args.port}")
  print(f"DB: {db_path}")
  try:
    httpd.serve_forever()
  except KeyboardInterrupt:
    print("\nShutting down...")
  finally:
    httpd.server_close()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
