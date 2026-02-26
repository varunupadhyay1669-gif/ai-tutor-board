import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _pick_free_port() -> int:
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(("127.0.0.1", 0))
    return int(s.getsockname()[1])


def _wait_for_health(url: str, timeout_s: float = 10.0) -> None:
  import urllib.request

  deadline = time.time() + timeout_s
  last_err = None
  while time.time() < deadline:
    try:
      with urllib.request.urlopen(url + "/api/health", timeout=2) as resp:
        if resp.status == 200:
          return
    except Exception as e:  # noqa: BLE001
      last_err = e
      time.sleep(0.15)
  raise RuntimeError(f"Server did not become healthy: {last_err}")


@pytest.fixture(scope="session")
def server_base_url(tmp_path_factory):
  port = _pick_free_port()
  db_path = tmp_path_factory.mktemp("ti_db") / "test.sqlite3"
  base_url = f"http://127.0.0.1:{port}"

  env = os.environ.copy()
  env.pop("TRANSCRIPT_INTEL_DB", None)

  proc = subprocess.Popen(
    [sys.executable, "-m", "transcript_intel.server", "--host", "127.0.0.1", "--port", str(port), "--db", str(db_path)],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    env=env,
    cwd=str(Path(__file__).resolve().parents[2]),
    text=True,
  )
  try:
    _wait_for_health(base_url, timeout_s=12.0)
    yield base_url
  finally:
    proc.terminate()
    try:
      proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
      proc.kill()


@pytest.fixture()
def page(server_base_url):
  from playwright.sync_api import sync_playwright

  with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(server_base_url, wait_until="domcontentloaded")
    yield page
    browser.close()


def test_trial_transcript_creates_goal_tree_and_topics(page):
  page.fill("#trialName", "Test Student")
  page.fill("#trialGrade", "7")
  page.fill("#trialCurriculum", "Common Core")
  page.fill("#trialDate", "2026-02-11")
  page.fill(
    "#trialTranscript",
    "Parent: Our goal is to get better at fractions.\nStudent: I get stuck with negative numbers.\nTutor: We'll improve fractions and equations.",
  )
  page.click("#btnProcessTrial")
  page.wait_for_selector("#trialStatus")
  page.wait_for_timeout(250)
  assert "Created student" in page.inner_text("#trialStatus")

  # Dashboard should show seeded topics and the student name.
  meta = page.inner_text("#dashboardMeta")
  assert "Test Student" in meta
  assert page.locator('[data-topic="Fractions"]').count() == 1


def test_session_transcript_updates_mastery(page):
  # Reuse the student created in the previous test by selecting it.
  page.wait_for_timeout(250)
  page.select_option("#studentSelect", label="Test Student (Grade 7)")
  page.wait_for_timeout(250)

  fractions = page.locator('[data-topic="Fractions"]')
  before = int(fractions.get_attribute("data-mastery") or "0")

  page.fill("#sessionDate", "2026-02-12")
  page.fill("#sessionTranscript", "Tutor: Add 1/4 + 1/4.\nStudent: 1/2")
  page.click("#btnProcessSession")
  page.wait_for_timeout(400)
  assert "processed" in page.inner_text("#sessionStatus").lower()

  after = int(fractions.get_attribute("data-mastery") or "0")
  assert after >= before


def test_repeated_mistake_three_sessions_creates_mental_block(page):
  page.select_option("#studentSelect", label="Test Student (Grade 7)")
  page.wait_for_timeout(250)

  for i in range(3):
    page.fill("#sessionDate", f"2026-02-1{3 + i}")
    page.fill(
      "#sessionTranscript",
      "Tutor: Add 1/3 + 1/6.\nStudent: I think you add the denominators.\nTutor: hint: common denominator.\nStudent: got it.",
    )
    page.click("#btnProcessSession")
    page.wait_for_timeout(350)

  # After 3 sessions, the mental block should appear.
  block = page.locator('[data-mental-block="Adds denominators when working with fractions"]')
  assert block.count() == 1

