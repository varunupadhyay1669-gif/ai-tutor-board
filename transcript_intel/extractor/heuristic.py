from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, Optional

from ..growth import GrowthConfig, update_mastery_and_confidence
from .base import (
  SessionExtractRequest,
  SessionExtractResult,
  TranscriptExtractor,
  TrialExtractRequest,
  TrialExtractResult,
)


TOPIC_TAXONOMY: dict[str, dict[str, Any]] = {
  "Arithmetic": {
    "Fractions": ["fraction", "numerator", "denominator", "common denominator", "simplify", "mixed number"],
    "Decimals": ["decimal", "place value", "tenths", "hundredths", "thousandths"],
    "Percents": ["percent", "%", "percentage"],
    "Integers": ["integer", "negative", "positive", "absolute value", "number line"],
    "Ratios & Rates": ["ratio", "rate", "unit rate", "proportion", "scale"],
  },
  "Algebra": {
    "Expressions": ["expression", "distribute", "combine like terms", "simplify expression"],
    "Equations": ["equation", "solve for", "isolate", "variable", "x =", "y ="],
    "Linear Equations": ["linear", "slope", "y-intercept", "mx+b", "rise over run"],
    "Functions": ["function", "f(x)", "domain", "range", "input", "output"],
    "Exponents & Radicals": ["exponent", "power", "square root", "radical", "scientific notation"],
    "Quadratics": ["quadratic", "parabola", "vertex", "factor", "complete the square"],
  },
  "Geometry": {
    "Angles": ["angle", "vertical angles", "complementary", "supplementary", "parallel", "transversal"],
    "Triangles": ["triangle", "isosceles", "equilateral", "right triangle", "pythagorean", "similar", "congruent"],
    "Circles": ["circle", "radius", "diameter", "circumference", "arc", "chord", "tangent"],
    "Area & Perimeter": ["area", "perimeter", "volume", "surface area"],
    "Coordinate Geometry": ["coordinate", "graph", "slope", "distance formula", "midpoint"],
  },
  "Data & Probability": {
    "Statistics": ["mean", "median", "mode", "range", "standard deviation", "box plot", "histogram"],
    "Probability": ["probability", "chance", "likely", "outcome", "sample space"],
  },
  "Word Problems": {
    "Translation": ["word problem", "translate", "given", "find", "let", "represents"],
  },
}


NEGATIVE_CONFIDENCE_PATTERNS = [
  r"\bi don't know\b",
  r"\bnot sure\b",
  r"\bconfus(ed|ing)\b",
  r"\bstuck\b",
  r"\bi can't\b",
  r"\bthis is hard\b",
  r"\bI'm bad at\b",
]

AVOIDANCE_PATTERNS = [
  r"\bi hate\b",
  r"\bi always\b",
  r"\bi never\b",
  r"\bi give up\b",
  r"\bcan we not\b",
]

POSITIVE_CONFIDENCE_PATTERNS = [
  r"\bg(o|o)t it\b",
  r"\bmakes sense\b",
  r"\bokay\b",
  r"\bi understand\b",
  r"\bthat was easy\b",
]

GOAL_CUES = [
  r"\bgoal\b",
  r"\bwant to\b",
  r"\btrying to\b",
  r"\bneed to\b",
  r"\bimprove\b",
  r"\bget better\b",
  r"\bscore\b",
]

STRUGGLE_CUES = [
  r"\bstruggle\b",
  r"\bhard for me\b",
  r"\bkeeps? mess(ing)? up\b",
  r"\bconfus(ed|ing)\b",
]


def _norm(text: str) -> str:
  return re.sub(r"\s+", " ", (text or "").strip())


def _findall_any(patterns: list[str], text: str) -> list[str]:
  hits: list[str] = []
  for p in patterns:
    if re.search(p, text, flags=re.IGNORECASE):
      hits.append(p)
  return hits


def _count_any(patterns: list[str], text: str) -> int:
  count = 0
  for p in patterns:
    count += len(re.findall(p, text, flags=re.IGNORECASE))
  return count


def _extract_goal_lines(text: str) -> list[str]:
  lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
  goal_lines: list[str] = []
  cue_re = re.compile("|".join(GOAL_CUES), re.IGNORECASE)
  for l in lines:
    if cue_re.search(l):
      goal_lines.append(_norm(l))
  return goal_lines[:10]


def _extract_struggle_lines(text: str) -> list[str]:
  lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
  cue_re = re.compile("|".join(STRUGGLE_CUES), re.IGNORECASE)
  out: list[str] = []
  for l in lines:
    if cue_re.search(l):
      out.append(_norm(l))
  return out[:10]


def _detect_topics_in_text(text: str) -> dict[str, dict[str, Any]]:
  text_l = (text or "").lower()
  scores: dict[str, dict[str, Any]] = {}
  for parent, children in TOPIC_TAXONOMY.items():
    for topic, keywords in children.items():
      hit_count = 0
      hits: list[str] = []
      for kw in keywords:
        kw_l = kw.lower()
        if kw_l in text_l:
          hit_count += text_l.count(kw_l)
          hits.append(kw)
      if hit_count > 0:
        scores[topic] = {"topic_name": topic, "parent_topic": parent, "hit_count": hit_count, "hits": hits}

  # Regex-based topic signals (common transcript shorthand).
  if re.search(r"\b\d+\s*/\s*\d+\b", text or ""):
    cur = scores.get("Fractions") or {"topic_name": "Fractions", "parent_topic": "Arithmetic", "hit_count": 0, "hits": []}
    cur["hit_count"] = int(cur["hit_count"]) + 2
    cur["hits"] = list(cur.get("hits") or []) + ["<fraction a/b>"]
    scores["Fractions"] = cur

  if "%" in (text or ""):
    cur = scores.get("Percents") or {"topic_name": "Percents", "parent_topic": "Arithmetic", "hit_count": 0, "hits": []}
    cur["hit_count"] = int(cur["hit_count"]) + 1
    cur["hits"] = list(cur.get("hits") or []) + ["%"]
    scores["Percents"] = cur

  if re.search(r"\b[xy]\s*=\s*[-+]?\d+", text_l):
    cur = scores.get("Equations") or {"topic_name": "Equations", "parent_topic": "Algebra", "hit_count": 0, "hits": []}
    cur["hit_count"] = int(cur["hit_count"]) + 1
    cur["hits"] = list(cur.get("hits") or []) + ["x=.../y=..."]
    scores["Equations"] = cur
  return scores


def _split_turns(text: str) -> list[dict[str, str]]:
  raw_lines = [l.rstrip() for l in (text or "").splitlines()]
  turns: list[dict[str, str]] = []

  speaker_re = re.compile(r"^\s*(Tutor|Student|Parent)\s*:\s*(.*)$", re.IGNORECASE)
  current = {"speaker": "Unknown", "text": ""}
  for line in raw_lines:
    m = speaker_re.match(line)
    if m:
      if current["text"].strip():
        turns.append({"speaker": current["speaker"], "text": _norm(current["text"])})
      current = {"speaker": m.group(1).title(), "text": m.group(2)}
    else:
      current["text"] += "\n" + line
  if current["text"].strip():
    turns.append({"speaker": current["speaker"], "text": _norm(current["text"])})

  if not turns and (text or "").strip():
    turns = [{"speaker": "Unknown", "text": _norm(text)}]

  return turns


def _infer_milestones_from_goals(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
  milestones: list[dict[str, Any]] = []
  for g in goals[:10]:
    desc = str(g.get("description") or "").strip()
    if not desc:
      continue
    milestones.append(
      {
        "goal_description": desc,
        "milestone": "Baseline check-in and identify top 3 gaps",
        "success_criteria": "Tutor has a clear topic gap list + baseline accuracy estimate",
      }
    )
    milestones.append(
      {
        "goal_description": desc,
        "milestone": "Midpoint: consistent accuracy with light prompting",
        "success_criteria": "Student solves most problems with 1 hint or fewer",
      }
    )
    milestones.append(
      {
        "goal_description": desc,
        "milestone": "Target: independent solving under time pressure",
        "success_criteria": "Student solves independently with minimal hesitation",
      }
    )
  return milestones


def _infer_roadmap(
  *,
  grade: Optional[str],
  curriculum: Optional[str],
  target_exam: Optional[str],
  mentioned_topics: list[dict[str, Any]],
) -> dict[str, Any]:
  grade_n = _norm(grade or "")
  exam_n = _norm(target_exam or "")
  cur_n = _norm(curriculum or "")

  focus: list[str] = []
  if exam_n:
    if re.search(r"\bSAT\b", exam_n, re.IGNORECASE) or re.search(r"\bACT\b", exam_n, re.IGNORECASE):
      focus = ["Algebra", "Geometry", "Data & Probability", "Word Problems"]
  if not focus:
    focus = ["Arithmetic", "Algebra", "Geometry"]

  topics = []
  for parent in focus:
    children = TOPIC_TAXONOMY.get(parent, {})
    for topic_name in children.keys():
      topics.append({"parent_topic": parent, "topic_name": topic_name})

  # Prioritize any mentioned topics to the top of their parent bucket.
  mentioned = {(t["parent_topic"], t["topic_name"]) for t in mentioned_topics}
  topics.sort(key=lambda x: (0 if (x["parent_topic"], x["topic_name"]) in mentioned else 1, x["parent_topic"], x["topic_name"]))

  return {
    "grade": grade_n or None,
    "curriculum": cur_n or None,
    "target_exam": exam_n or None,
    "focus_domains": focus,
    "topics": topics,
  }


class HeuristicTranscriptExtractor(TranscriptExtractor):
  def __init__(self, *, config: Optional[GrowthConfig] = None):
    self.config = config or GrowthConfig()

  def extract_trial(self, req: TrialExtractRequest) -> TrialExtractResult:
    text = req.transcript_text or ""
    goal_lines = _extract_goal_lines(text)
    struggle_lines = _extract_struggle_lines(text)
    topic_scores = _detect_topics_in_text(text)

    goals: list[dict[str, Any]] = []
    for gl in goal_lines:
      goals.append(
        {
          "description": gl,
          "measurable_outcome": "Show measurable improvement across weekly checks (accuracy + independence).",
          "deadline": None,
          "status": "not started",
        }
      )

    for sl in struggle_lines:
      # Convert struggle statements into an implicit goal.
      goals.append(
        {
          "description": f"Reduce recurring difficulty: {sl}",
          "measurable_outcome": "Student solves similar problems with 80%+ accuracy and 1 hint or fewer.",
          "deadline": None,
          "status": "not started",
        }
      )

    if not goals:
      goals.append(
        {
          "description": "Build consistent math confidence and mastery over time.",
          "measurable_outcome": "Mastery and confidence trend upward across the topic map.",
          "deadline": None,
          "status": "not started",
        }
      )

    mentioned_topics = sorted(topic_scores.values(), key=lambda x: (-int(x["hit_count"]), x["parent_topic"], x["topic_name"]))
    inferred = _infer_roadmap(
      grade=req.grade,
      curriculum=req.curriculum,
      target_exam=req.target_exam,
      mentioned_topics=mentioned_topics,
    )

    topics: list[dict[str, Any]] = []
    for t in inferred["topics"]:
      # Seed mastery a little higher if explicitly mentioned in the trial.
      seed = 25 if any(mt["topic_name"] == t["topic_name"] for mt in mentioned_topics) else 15
      topics.append(
        {
          "topic_name": t["topic_name"],
          "parent_topic": t["parent_topic"],
          "mastery_score": seed,
          "confidence_score": 50,
        }
      )

    summary_bits = []
    if goal_lines:
      summary_bits.append(f"Goals mentioned: {', '.join(goal_lines[:3])}")
    if struggle_lines:
      summary_bits.append(f"Common challenges: {', '.join(struggle_lines[:3])}")
    if mentioned_topics:
      summary_bits.append(f"Topics discussed: {', '.join([t['topic_name'] for t in mentioned_topics[:4]])}")
    long_term_goal_summary = _norm(" • ".join(summary_bits)) or "Trial goals and roadmap captured."

    milestones = _infer_milestones_from_goals(goals)

    return TrialExtractResult(
      long_term_goal_summary=long_term_goal_summary,
      goals=goals,
      topics=topics,
      milestones=milestones,
      inferred_curriculum_roadmap=inferred,
      debug={
        "topic_scores": mentioned_topics[:10],
        "goal_lines": goal_lines,
        "struggle_lines": struggle_lines,
      },
    )

  def extract_session(self, req: SessionExtractRequest) -> SessionExtractResult:
    text = req.transcript_text or ""
    turns = _split_turns(text)

    topic_scores = _detect_topics_in_text(text)
    detected_topics = [t["topic_name"] for t in sorted(topic_scores.values(), key=lambda x: (-int(x["hit_count"]), x["topic_name"]))][:8]

    confidence_neg = _count_any(NEGATIVE_CONFIDENCE_PATTERNS, text)
    confidence_pos = _count_any(POSITIVE_CONFIDENCE_PATTERNS, text)
    avoidance = _count_any(AVOIDANCE_PATTERNS, text)

    engagement = 70 + (confidence_pos * 4) - (confidence_neg * 6) - (avoidance * 10)
    engagement_score = max(0, min(100, int(engagement)))

    detected_misconceptions: list[str] = []
    misconception_patterns = [
      (r"add(ing)? the denominators", "Adds denominators when working with fractions"),
      (r"cross[- ]multiply", "Uses cross-multiplication incorrectly or in the wrong context"),
      (r"sign error|wrong sign|forgot the negative", "Sign error with negatives"),
      (r"distribut(e|ion)", "Distribution mistakes (missed a term or sign)"),
    ]
    for pat, label in misconception_patterns:
      if re.search(pat, text, flags=re.IGNORECASE):
        detected_misconceptions.append(label)

    detected_strengths: list[str] = []
    strength_patterns = [
      (r"\bgot it\b", "Understands after explanation"),
      (r"\bsolved\b|\bI did\b", "Completes problems to a final answer"),
      (r"\bchecks? my work\b|\bdouble[- ]check\b", "Shows self-checking behavior"),
    ]
    for pat, label in strength_patterns:
      if re.search(pat, text, flags=re.IGNORECASE):
        detected_strengths.append(label)

    extracted_summary = "Topics covered: " + (", ".join(detected_topics) if detected_topics else "General problem solving")

    # Build per-topic signals from turns so the scoring stays explainable.
    per_topic_signals: dict[str, dict[str, Any]] = {}
    for known in req.known_topics:
      name = str(known.get("topic_name") or "").strip()
      if not name:
        continue
      per_topic_signals[name] = {
        "attempt_count": 0,
        "error_count": 0,
        "repeated_error_count": 0,
        "independent_count": 0,
        "hint_count": 0,
        "confidence_positive": 0,
        "confidence_negative": 0,
      }

    # Ensure we can update newly-detected topics even if they weren't in the DB yet.
    for t in detected_topics:
      if t not in per_topic_signals:
        per_topic_signals[t] = {
          "attempt_count": 0,
          "error_count": 0,
          "repeated_error_count": 0,
          "independent_count": 0,
          "hint_count": 0,
          "confidence_positive": 0,
          "confidence_negative": 0,
        }

    hint_re = re.compile(r"\b(hint|remember|try|think about|let's)\b", re.IGNORECASE)
    neg_re = re.compile("|".join(NEGATIVE_CONFIDENCE_PATTERNS), re.IGNORECASE)
    pos_re = re.compile("|".join(POSITIVE_CONFIDENCE_PATTERNS), re.IGNORECASE)
    answerish_re = re.compile(r"(=|\banswer\b|\bso\b|\btherefore\b)", re.IGNORECASE)
    numeric_answer_re = re.compile(r"\b\d+\s*/\s*\d+\b|\b-?\d+(?:\.\d+)?\b")

    topic_kw_map: dict[str, list[str]] = {}
    for parent, children in TOPIC_TAXONOMY.items():
      for topic, kws in children.items():
        topic_kw_map[topic] = kws

    for turn in turns:
      speaker = turn["speaker"]
      ttext = turn["text"]
      t_l = ttext.lower()
      matched_topics: list[str] = []
      for topic, kws in topic_kw_map.items():
        if any(kw.lower() in t_l for kw in kws):
          matched_topics.append(topic)

      if re.search(r"\b\d+\s*/\s*\d+\b", ttext):
        matched_topics.append("Fractions")
      if "%" in ttext:
        matched_topics.append("Percents")
      if re.search(r"\b[xy]\s*=\s*[-+]?\d+", t_l):
        matched_topics.append("Equations")

      if matched_topics:
        matched_topics = sorted(set(matched_topics))

      if not matched_topics:
        continue

      for topic in matched_topics:
        sig = per_topic_signals.get(topic)
        if not sig:
          continue

        if speaker == "Tutor":
          if hint_re.search(ttext):
            sig["hint_count"] += 1
          continue

        # Student (or unknown) turn.
        sig["attempt_count"] += 1
        if neg_re.search(ttext) or "?" in ttext:
          sig["error_count"] += 1
          sig["confidence_negative"] += 1
        if pos_re.search(ttext):
          sig["confidence_positive"] += 1
        looks_like_final_answer = answerish_re.search(ttext) or (
          numeric_answer_re.search(ttext) and len(ttext) <= 60 and ("\n" not in ttext)
        )
        if looks_like_final_answer and not neg_re.search(ttext) and "?" not in ttext:
          sig["independent_count"] += 1

    # Flag repeated errors if a misconception shows up in recent sessions too.
    recent_mis = []
    for s in req.recent_sessions[:10]:
      for m in (s.get("detected_misconceptions") or []):
        recent_mis.append(str(m))
    for m in detected_misconceptions:
      repeats = sum(1 for x in recent_mis if x == m)
      if repeats > 0:
        # Apply the repeat penalty to any topic that was discussed.
        for t in detected_topics:
          per_topic_signals.setdefault(t, {}).setdefault("repeated_error_count", 0)
          per_topic_signals[t]["repeated_error_count"] += 1

    # Compute per-topic update suggestions (server applies them to DB).
    per_topic_updates: dict[str, dict[str, Any]] = {}
    known_topic_by_name = {str(t.get("topic_name")): t for t in req.known_topics}
    active_topics: set[str] = set(detected_topics)
    for topic, sig in per_topic_signals.items():
      if (
        int(sig.get("attempt_count") or 0)
        + int(sig.get("error_count") or 0)
        + int(sig.get("hint_count") or 0)
        + int(sig.get("independent_count") or 0)
        + int(sig.get("repeated_error_count") or 0)
        + int(sig.get("confidence_positive") or 0)
        + int(sig.get("confidence_negative") or 0)
      ) > 0:
        active_topics.add(topic)

    for topic in sorted(active_topics):
      sig = per_topic_signals.get(topic) or {
        "attempt_count": 0,
        "error_count": 0,
        "repeated_error_count": 0,
        "independent_count": 0,
        "hint_count": 0,
        "confidence_positive": 0,
        "confidence_negative": 0,
      }
      prev = known_topic_by_name.get(topic, {"mastery_score": 15, "confidence_score": 50})
      new_mastery, new_conf, explanation = update_mastery_and_confidence(
        previous_mastery=int(prev.get("mastery_score") or 0),
        previous_confidence=int(prev.get("confidence_score") or 0),
        signals=sig,
        config=self.config,
      )
      per_topic_updates[topic] = {
        "previous_mastery": int(prev.get("mastery_score") or 0),
        "new_mastery": int(new_mastery),
        "previous_confidence": int(prev.get("confidence_score") or 0),
        "new_confidence": int(new_conf),
        "explanation": explanation,
      }

    parent_summary = (
      f"Today we worked on {', '.join(detected_topics[:3]) if detected_topics else 'problem solving'}."
      + (" Your student showed growing confidence." if confidence_pos >= confidence_neg else " We identified a few areas to strengthen.")
    )
    tutor_insight = (
      f"Signals: engagement={engagement_score}/100, confidence_pos={confidence_pos}, confidence_neg={confidence_neg}, avoidance={avoidance}. "
      f"Misconceptions: {', '.join(detected_misconceptions) if detected_misconceptions else 'none detected'}."
    )

    # Recommend next targets: low mastery among detected topics first, otherwise overall low mastery.
    def _topic_sort_key(name: str) -> tuple[int, str]:
      prev_m = int(known_topic_by_name.get(name, {}).get("mastery_score") or 15)
      return (prev_m, name)

    rec = sorted(detected_topics, key=_topic_sort_key)[:3]
    if len(rec) < 3:
      all_known = sorted(known_topic_by_name.keys(), key=_topic_sort_key)
      for t in all_known:
        if t not in rec:
          rec.append(t)
        if len(rec) >= 3:
          break

    # Mental block candidates: repeated misconception threshold or avoidance language.
    mental_block_candidates: list[dict[str, Any]] = []
    total_sessions_with_mis = {m: 0 for m in detected_misconceptions}
    for s in req.recent_sessions[:25]:
      for m in (s.get("detected_misconceptions") or []):
        if m in total_sessions_with_mis:
          total_sessions_with_mis[m] += 1
    for m in detected_misconceptions:
      session_count = total_sessions_with_mis.get(m, 0) + 1
      if session_count >= self.config.mental_block_session_threshold or avoidance > 0:
        initial = self.config.mental_block_base_severity + (self.config.mental_block_avoidance_bonus if avoidance > 0 else 0)
        repeat_delta = self.config.mental_block_repeat_delta + (self.config.mental_block_avoidance_bonus if avoidance > 0 else 0)
        mental_block_candidates.append(
          {
            "description": m,
            "session_count": session_count,
            "avoidance_signals": avoidance,
            "initial_severity": int(initial),
            "repeat_severity_delta": int(repeat_delta),
          }
        )

    return SessionExtractResult(
      extracted_summary=extracted_summary,
      detected_topics=detected_topics,
      detected_misconceptions=detected_misconceptions,
      detected_strengths=detected_strengths,
      engagement_score=engagement_score,
      parent_summary=parent_summary,
      tutor_insight=tutor_insight,
      recommended_next_targets=rec,
      per_topic_signals={k: per_topic_signals[k] for k in sorted(active_topics) if k in per_topic_signals},
      per_topic_updates=per_topic_updates,
      mental_block_candidates=mental_block_candidates,
      debug={
        "turn_count": len(turns),
        "topic_scores": sorted(topic_scores.values(), key=lambda x: (-int(x["hit_count"]), x["topic_name"]))[:10],
        "config": asdict(self.config),
      },
    )
