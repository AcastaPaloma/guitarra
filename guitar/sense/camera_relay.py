"""Camera relay: grab frames continuously, serve the latest one over localhost HTTP.

Run it from Terminal.app (which can get macOS camera permission); anything else - the Astra
loop, scripts, Claude - reads frames over HTTP without needing camera access itself.

    python sense/camera_relay.py --index 1          # 1 = Camo Camera (iPad) on this Mac

Endpoints (127.0.0.1 only):
    /frame.jpg   latest frame, full resolution
    /astra.jpg   latest frame as Astra gets it: 768 px wide, JPEG q70 (SETUP.md §2)
    /stream      MJPEG live view - open in a browser to aim the camera
    /health      JSON: resolution, fps, age of latest frame
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

ap = argparse.ArgumentParser()
ap.add_argument("--index", type=int, default=1, help="OpenCV camera index (1 = Camo Camera here)")
ap.add_argument("--width", type=int, default=1280)
ap.add_argument("--height", type=int, default=720)
ap.add_argument("--port", type=int, default=8765)
args = ap.parse_args()

lock = threading.Lock()
latest = {"frame": None, "t": 0.0, "fps": 0.0}


def open_camera() -> cv2.VideoCapture:
    # Must run on the main thread: that's the only place OpenCV can trigger the macOS
    # camera-permission prompt. Retry while the user is answering it.
    for _ in range(30):
        cap = cv2.VideoCapture(args.index, cv2.CAP_AVFOUNDATION)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
            return cap
        cap.release()
        time.sleep(2)
    raise SystemExit(f"cannot open camera {args.index} - camera permission for Terminal? Camo running?")


def capture_loop(cap: cv2.VideoCapture):
    n, t0 = 0, time.monotonic()
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.05)
            continue
        n += 1
        now = time.monotonic()
        with lock:
            latest["frame"], latest["t"] = frame, now
            if now - t0 >= 1.0:
                latest["fps"], n, t0 = n / (now - t0), 0, now


def encode(astra: bool) -> bytes | None:
    with lock:
        frame = latest["frame"]
    if frame is None:
        return None
    if astra:
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (768, round(h * 768 / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70 if astra else 90])
    return buf.tobytes() if ok else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/frame.jpg", "/astra.jpg"):
            jpg = encode(astra=self.path == "/astra.jpg")
            if jpg is None:
                return self._send(b"no frame yet", "text/plain", 503)
            return self._send(jpg, "image/jpeg")
        if self.path == "/health":
            with lock:
                f = latest["frame"]
                info = {
                    "index": args.index,
                    "shape": None if f is None else list(f.shape),
                    "fps": round(latest["fps"], 1),
                    "age_s": None if f is None else round(time.monotonic() - latest["t"], 3),
                }
            return self._send(json.dumps(info).encode(), "application/json")
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    jpg = encode(astra=False)
                    if jpg:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")
                    time.sleep(1 / 30)
            except (BrokenPipeError, ConnectionResetError):
                return
        self._send(b"try /stream /frame.jpg /astra.jpg /health", "text/plain", 404)


cap = open_camera()
server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
print(f"camera {args.index} -> http://127.0.0.1:{args.port}/stream   (Ctrl-C to stop)")
capture_loop(cap)
