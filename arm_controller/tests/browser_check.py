"""Offline browser regression: ALL APIs intercepted, oscillator microphone only.

No serial, real microphone, Baseten, or physical timing/quality evidence. Requires
optional Playwright and installed Google Chrome; serves only static app assets.
"""
import argparse
import io
import json
import time
import wave
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

INIT = """(() => {
  window.testTracks = []; window.testMicCalls = [];
  navigator.mediaDevices.getUserMedia = async constraints => {
    window.testMicCalls.push(constraints);
    if (window.testMode === 'deny') throw new DOMException('fixture denied', 'NotAllowedError');
    if (window.testMode === 'late') await new Promise(r => setTimeout(r, 700));
    // Do NOT call the real getUserMedia API, even with Chromium fake-device flags.
    const ctx = new AudioContext(); await ctx.resume();
    const destination = ctx.createMediaStreamDestination(), oscillator = ctx.createOscillator();
    oscillator.frequency.value = 220; oscillator.connect(destination); oscillator.start();
    const stream = destination.stream;
    for (const track of stream.getTracks()) {
      const stop = track.stop.bind(track); let ended = false;
      track.stop = () => { if (ended) return; ended = true; stop(); oscillator.stop(); void ctx.close(); };
    }
    window.testTracks.push(...stream.getTracks()); return stream;
  };
})();"""
SESSION = "00000000-0000-0000-0000-000000000100"


class Fixture:
    def __init__(self, mode="success"):
        self.mode, self.plays, self.uploads, self.partials = mode, 0, 0, 0
        self.records, self.requests = [], []
        self.preferred = None

    @staticmethod
    def public(record):
        return {k: v for k, v in record.items() if not k.startswith("_")}

    def history(self):
        rows = []
        for record in self.records:
            completed = record["playback_outcome"] == "completed"
            rows.append({**self.public(record), "tuning_id": str(record["plan"]["notes"][0]["pause_ms"]),
                         "command_elapsed_s": record.get("playback_elapsed_s") if completed else None,
                         "command_delta_from_first_s": 0 if completed else None,
                         "same_phrase_and_calibration": completed, "audio_available": "_wav" in record,
                         "audio_incomplete": bool(record.get("_partial")), "can_load_tuning": completed,
                         "preferred_by_operator": record["attempt_id"] == self.preferred})
        return {"session_id": SESSION, "title": "Offline UI fixture", "takes": rows, "max_session_takes": 100}

    def find(self, attempt_id):
        return next(r for r in self.records if r["attempt_id"] == attempt_id)

    def route(self, route):
        request, response = route.request, None
        path = urlsplit(request.url).path
        self.requests.append((request.method, path))
        if path == "/api/bootstrap":
            response = {"session_token": "offline-fixture", "keys": [
                {"string": 1, "fret": 1, "pitch": "F4"}, {"string": 1, "fret": 2, "pitch": "F#4"}],
                "warning": "OFFLINE UI FIXTURE — not a real performance or assessment.",
                "max_take_notes": 4, "max_attempts": 3, "max_capture_seconds": 60,
                "path_profiles": ["lift_first"], "preferred_path_profile": "lift_first",
                "paths_ready": self.mode != "missing_path", "recorded_hover_count": 2,
                "path_blocker": "Fixture missing hover review" if self.mode == "missing_path" else None,
                "key_present": True, "audio_model_supported": True, "active_attempt": None,
                "planner_model": "mock", "audio_model": "mock", "audio_endpoint_status": "mocked only"}
        elif path == "/api/sessions":
            response = {"sessions": [{"session_id": SESSION, "title": "Offline UI fixture", "take_count": len(self.records)}] if self.records else []}
        elif path == f"/api/sessions/{SESSION}":
            response = self.history()
        elif path == f"/api/sessions/{SESSION}/preferred":
            self.preferred = request.post_data_json["attempt_id"]
            response = self.history()
        elif path == "/api/plan":
            response = {"title": "Offline UI fixture", "notes": [
                {"string": 1, "fret": 1, "pause_ms": 250}, {"string": 1, "fret": 2, "pause_ms": 250}]}
        elif path == "/api/trajectory":
            notes = request.post_data_json["plan"]["notes"]
            response = {"executable": self.mode != "missing_path",
                        "blockers": ["Fixture missing hover review"] if self.mode == "missing_path" else [],
                        "trajectory": {"neutral_visits_between_notes": 0, "joint_travel_proxy_counts": 400,
                            "exit_route": ["rest"], "assignments": [{"arm": n["arm"]} for n in notes],
                            "notes": [{**n, "stages": [{"stage": "travel", "pose": f"hover-r{n['fret']}-c{n['string']}"},
                                {"stage": "tap", "pose": f"key-r{n['fret']}-c{n['string']}"},
                                {"stage": "lift_clear", "pose": f"hover-r{n['fret']}-c{n['string']}"}]} for n in notes]}}
        elif path == "/api/attempts":
            body = request.post_data_json
            assert body["allow_audio_upload"] and body["allow_revision_inference"] and body["supervised_and_supported"]
            record = {"attempt_id": f"00000000-0000-0000-0000-{len(self.records) + 1:012d}",
                      "capture_id": "00000000-0000-0000-0000-000000000200", "phase": "ready",
                      "session_id": SESSION, "take_number": len(self.records) + 1,
                      "plan": body["plan"], "parent_attempt_id": body.get("parent_attempt_id"),
                      "index": -1, "total": 2, "completed_notes": 0, "attempt_number": 1, "max_attempts": 3,
                      "playback_outcome": "not_started", "assessment": None, "revision": None,
                      "error": None, "stop_requested": False, "_review_polls": 0}
            self.records.append(record); response = self.public(record)
        elif path == "/api/play":
            body = request.post_data_json
            assert body["capture_ready"] and body["dispatch_frame"] > 0
            record = self.find(body["attempt_id"])
            self.plays += 1
            record.update(phase="playing", index=0, playback_outcome="running", _start=time.monotonic(), capture_start=body)
            response = self.public(record)
        elif path.endswith("/heartbeat"):
            response = {"phase": self.find(path.split('/')[3])["phase"]}
        elif path.endswith(("/audio", "/partial-audio")):
            record = self.find(path.split('/')[3])
            if request.method == "GET":
                assert request.headers.get("x-session-token") == "offline-fixture"
                route.fulfill(status=200, content_type="audio/wav", body=record["_wav"])
                return
            metadata = json.loads(request.headers["x-capture-metadata"])
            with wave.open(io.BytesIO(request.post_data_buffer), "rb") as wav:
                assert wav.getsampwidth() == 2 and wav.getnchannels() == 1
                assert wav.getframerate() == metadata["sample_rate"] and wav.getnframes() == metadata["frames"]
                assert len(wav.readframes(wav.getnframes())) == metadata["frames"] * 2
            record["_wav"] = request.post_data_buffer
            if path.endswith("/partial-audio"):
                assert record["stop_requested"] and metadata["incomplete"]
                record["_partial"] = True; self.partials += 1
                response = {"saved_locally": True, "incomplete": True, "uploaded_to_baseten": False}
            else:
                assert record["phase"] == "awaiting_audio"
                assert 0 < metadata["dispatch_frame"] < metadata["completion_frame"] <= metadata["frames"]
                self.uploads += 1; record["phase"] = "reviewing"; response = self.public(record)
        elif path == "/api/stop":
            record = self.find(request.post_data_json["attempt_id"])
            record.update(phase="stopped", stop_requested=True, playback_outcome="stopped", error="Fixture stop.")
            response = self.public(record)
        elif path == "/api/status":
            response = {"active_attempt": None}
        elif path.startswith("/api/attempts/"):
            record = self.find(path.split('/')[3])
            if record["phase"] == "playing" and time.monotonic() - record["_start"] > (10 if self.mode == "stop" else 0.7):
                record.update(phase="awaiting_audio", index=1, completed_notes=2, playback_outcome="completed", playback_elapsed_s=0.7)
            if record["phase"] == "reviewing":
                record["_review_polls"] += 1
                if record["_review_polls"] > 1:
                    if self.mode == "unavailable": record.update(phase="unavailable", error="Fixture provider timeout; no retry.")
                    else:
                        notes = [dict(n) for n in record["plan"]["notes"]]; before = notes[0]["pause_ms"]; notes[0]["pause_ms"] += 50
                        record.update(phase="review_ready", assessment={
                            "recording_quality": "limited", "notes_match": "uncertain", "timing_match": "inconsistent",
                            "summary": "Synthetic fixture only. <script>window.injected=true</script>", "observations": [],
                            "limitations": ["Generated audio and mocked model, not acoustic evidence."]}, revision={
                            "decision": "revise", "rationale": "Fixture pause change; no proven improvement.",
                            "changes": [{"kind": "timing", "note_index": 0, "before_ms": before, "after_ms": before + 50}],
                            "inspection_notes": ["No shortcut is qualified."], "plan": {"notes": notes, "path_profile": "lift_first"}})
            response = self.public(record)
        if response is None:
            # NEVER fall through to a physical/model endpoint, even for unexpected requests.
            route.fulfill(status=404, content_type="application/json", body='{"detail":"No fixture route"}')
        else: route.fulfill(status=200, content_type="application/json", body=json.dumps(response))


def wait_js(page, expression, timeout=15):
    # Keep app CSP intact; Playwright wait_for_function uses eval in this Chrome.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate(expression): return
        page.wait_for_timeout(50)
    raise AssertionError(f"Browser condition timed out: {expression}")


def consent(page):
    expect(page.locator("#consent-dialog")).to_be_visible()
    page.locator("#media-consent").check(); page.locator("#supervised").check()
    page.locator("#confirm-play").click()


def run(url, output):
    evidence = {"source": "offline_browser_fixture", "hardware": False, "real_microphone": False,
                "live_inference": False, "cases": []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True,
                                     args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        for mode in ("success", "deny", "late", "stop", "unavailable", "disconnect", "missing_path"):
            context = browser.new_context(permissions=["microphone"]); context.add_init_script(INIT)
            page, errors = context.new_page(), []
            page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
            fixture = Fixture("stop" if mode == "disconnect" else mode)
            page.route("**/api/**", fixture.route); page.goto(url)
            page.evaluate("mode => { window.testMode = mode; }", mode)
            expect(page.locator("#convert")).to_be_enabled()
            assert page.evaluate("window.testMicCalls.length") == 0
            page.locator("#prompt").fill("Offline fixture only"); page.locator("#convert").click()
            expect(page.locator("#plan")).to_be_visible()
            if mode == "missing_path":
                expect(page.locator("#path-status")).to_contain_text("Playback blocked")
                expect(page.locator("#play")).to_be_disabled()
                assert page.evaluate("window.testMicCalls.length") == 0
                assert not fixture.records and fixture.plays == 0 and not errors
                evidence["cases"].append({"case": mode, "passed": True, "play_requests": 0,
                                          "microphone_requests": 0, "javascript_errors": errors})
                context.close()
                continue
            expect(page.locator("#play")).to_be_enabled()
            expect(page.locator("#path-status")).to_contain_text("No neutral between notes")
            page.locator("#play").click()
            assert fixture.plays == 0
            consent(page)
            if mode in {"stop", "disconnect"}:
                wait_js(page, "window.testTracks.length > 0")
                expect(page.locator("#status")).to_contain_text("Playing + listening")
                if mode == "stop": page.locator("#stop").click()
                else: page.evaluate("window.testTracks[0].dispatchEvent(new Event('ended'))")
            elif mode == "late":
                wait_js(page, "window.testMicCalls.length === 1"); page.locator("#stop").click()
            if mode == "success":
                expect(page.locator("#changes")).to_contain_text("250 → 300ms", timeout=15000)
                expect(page.locator("#selected")).to_contain_text("proposed")
                assert fixture.plays == 1 and fixture.uploads == 1
                assert page.evaluate("window.injected === undefined")
                page.locator("#play").click()
                expect(page.locator("#selected")).to_contain_text("300ms")
                page.wait_for_timeout(300); assert fixture.plays == 1  # confirmation is still required
                consent(page)
                expect(page.locator("#changes")).to_contain_text("300 → 350ms", timeout=15000)
                expect(page.locator("#history-count")).to_have_text("2")
                assert fixture.plays == 2 and fixture.uploads == 2
                page.locator("#history-tab").click()
                expect(page.locator(".take-row")).to_have_count(2)
                page.locator(".take-row").last.locator("button").filter(has_text="☆").click()
                expect(page.locator(".take-row.preferred")).to_have_count(1)
                page.locator(".take-row").last.get_by_role("button", name="listen", exact=True).click()
                expect(page.locator("#history-audio")).to_be_visible()
                page.locator(".take-row").last.get_by_role("button", name="use tuning", exact=True).click()
                expect(page.locator("#selected")).to_contain_text("250ms")
                assert fixture.plays == 2  # cache loading NEVER plays
                page.reload()
                expect(page.locator("#plan")).to_be_visible()
                expect(page.locator("#selected")).to_contain_text("250ms")  # persisted preferred tuning
                assert page.evaluate("window.testMicCalls.length") == 0
                for tab, suffix in (("play-tab", "play"), ("history-tab", "history")):
                    page.locator('#' + tab).click()
                    page.evaluate("document.getElementById('availability').textContent = 'OFFLINE UI FIXTURE · synthetic audio · no devices / live inference'")
                    for width in (1100, 390):
                        page.set_viewport_size({"width": width, "height": 900})
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        page.screenshot(path=str(output.with_name(f"{output.stem}-{suffix}-{width}.png")), full_page=True)
            elif mode == "unavailable":
                expect(page.locator("#status")).to_contain_text("Fixture provider timeout", timeout=15000)
                assert fixture.uploads == 1 and fixture.plays == 1
                expect(page.locator("#proposal")).to_be_hidden()
            else:
                expect(page.locator("#recording")).to_have_text("Mic off", timeout=15000)
                page.wait_for_timeout(1300)
                assert fixture.uploads == 0  # partial audio is local-only, never an evaluator request
                if mode in {"deny", "late"}: assert fixture.plays == 0
                if mode in {"stop", "disconnect"}: assert fixture.partials == 1
            wait_js(page, "window.testTracks.every(t => t.readyState === 'ended')")
            assert page.evaluate("window.testMicCalls.every(c => c.video === false)")
            assert not errors, errors
            evidence["cases"].append({"case": mode, "passed": True, "play_requests": fixture.plays,
                                      "completed_audio_uploads": fixture.uploads, "local_partial_clips": fixture.partials,
                                      "javascript_errors": errors})
            context.close()
        browser.close()
    output.write_text(json.dumps(evidence, indent=2)); print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8788")
    parser.add_argument("--output", type=Path, default=Path("guitar/runs/tap-browser-check.json"))
    args = parser.parse_args(); run(args.url, args.output)
