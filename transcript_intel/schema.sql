PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS student (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  grade TEXT,
  curriculum TEXT,
  target_exam TEXT,
  long_term_goal_summary TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS goal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL,
  description TEXT NOT NULL,
  measurable_outcome TEXT,
  deadline TEXT,
  status TEXT NOT NULL DEFAULT 'not started' CHECK (status IN ('not started','in progress','achieved')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS topic (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL,
  topic_name TEXT NOT NULL,
  parent_topic TEXT,
  mastery_score INTEGER NOT NULL DEFAULT 0 CHECK (mastery_score BETWEEN 0 AND 100),
  confidence_score INTEGER NOT NULL DEFAULT 0 CHECK (confidence_score BETWEEN 0 AND 100),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_unique_per_student ON topic(student_id, topic_name);
CREATE INDEX IF NOT EXISTS idx_topic_student_id ON topic(student_id);

CREATE TABLE IF NOT EXISTS session (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL,
  transcript_text TEXT NOT NULL,
  session_date TEXT NOT NULL,
  extracted_summary TEXT,
  detected_topics TEXT,
  detected_misconceptions TEXT,
  detected_strengths TEXT,
  engagement_score INTEGER,
  parent_summary TEXT,
  tutor_insight TEXT,
  recommended_next_targets TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_session_student_id ON session(student_id);
CREATE INDEX IF NOT EXISTS idx_session_date ON session(student_id, session_date);

CREATE TABLE IF NOT EXISTS mental_block (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL,
  description TEXT NOT NULL,
  first_detected TEXT NOT NULL,
  last_detected TEXT NOT NULL,
  frequency_count INTEGER NOT NULL DEFAULT 1,
  severity_score INTEGER NOT NULL DEFAULT 0 CHECK (severity_score BETWEEN 0 AND 100),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mental_block_unique_per_student ON mental_block(student_id, description);
CREATE INDEX IF NOT EXISTS idx_mental_block_student_id ON mental_block(student_id);

CREATE TABLE IF NOT EXISTS topic_mastery_event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL,
  topic_name TEXT NOT NULL,
  session_id INTEGER,
  event_date TEXT NOT NULL,
  previous_mastery INTEGER NOT NULL CHECK (previous_mastery BETWEEN 0 AND 100),
  new_mastery INTEGER NOT NULL CHECK (new_mastery BETWEEN 0 AND 100),
  previous_confidence INTEGER NOT NULL CHECK (previous_confidence BETWEEN 0 AND 100),
  new_confidence INTEGER NOT NULL CHECK (new_confidence BETWEEN 0 AND 100),
  explanation_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
  FOREIGN KEY (session_id) REFERENCES session(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_topic_event_student_id ON topic_mastery_event(student_id);
CREATE INDEX IF NOT EXISTS idx_topic_event_topic_date ON topic_mastery_event(student_id, topic_name, event_date);

