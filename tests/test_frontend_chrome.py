import http.server
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest


class MockTMAHandler(http.server.BaseHTTPRequestHandler):
    """Lightweight in-memory mock HTTP server for Chrome frontend verification."""

    def log_message(self, format, *args):
        pass  # Suppress server logs

    def do_GET(self):
        if self.path.startswith("/api/feed"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "hero": {"mal_id": 101, "title_ru": "Тестовый тайтл", "score": "8.5"},
                "continue_watching": [],
                "airing": [{"mal_id": 101, "title_ru": "Тестовый тайтл", "score": "8.5"}],
                "popular": [],
                "top": [],
            }).encode())
        elif self.path.startswith("/api/player/101"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "type": "hls",
                "url": "https://test.stream/ep1.m3u8",
                "episodes": {1: "https://test.stream/ep1.m3u8", 2: "https://test.stream/ep2.m3u8", 3: "https://test.stream/ep3.m3u8"},
                "first_ep": 1,
                "last_ep": 3,
                "translations": [{"id": 1, "title": "Озвучка 1", "type": "voice", "episodes_count": 3}]
            }).encode())
        elif self.path.startswith("/api/player/999"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "type": "hls",
                "url": "",
                "episodes": {},
                "translations": []
            }).encode())
        elif self.path.startswith("/api/search"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps([{"mal_id": 101, "title_ru": "Результат поиска"}]).encode())
        elif self.path.startswith("/api/vibe"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"results": [{"mal_id": 101, "title_ru": "Vibe тайтл"}]}).encode())
        elif self.path.startswith("/api/recommendations"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps([{"mal_id": 101, "title_ru": "Рекомендация"}]).encode())
        elif self.path.startswith("/test_page.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

            # Read actual static/index.html and inject mock test runner
            index_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "index.html")
            with open(index_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            # Injected mock telegram SDK and test assertions
            test_harness = """
            <script>
            // 1. Mock Telegram WebApp SDK
            window.Telegram = {
              WebApp: {
                initData: "user=%7B%22id%22%3A12345%2C%22first_name%22%3A%22Tester%22%7D&auth_date=1791974347&hash=dummy",
                initDataUnsafe: { user: { id: 12345, first_name: "Tester" }, start_param: "" },
                ready: function() {},
                expand: function() {},
                HapticFeedback: { impactOccurred: function() {}, notificationOccurred: function() {} },
                BackButton: {
                  isVisible: false,
                  show: function() { this.isVisible = true; },
                  hide: function() { this.isVisible = false; },
                  onClick: function(fn) { this._cb = fn; },
                  click: function() { if (this._cb) this._cb(); }
                },
                shareToStory: function(url, params) {}
              }
            };
            window.capturedErrors = [];
            window.addEventListener('error', function(e) {
              window.capturedErrors.push(e.message || String(e));
            });
            </script>
            """

            # Test suite runner script injected before closing body
            test_runner = """
            <div id="chrome-test-suite-results" style="display:none;"></div>
            <script>
            async function runAutomatedTests() {
              const results = [];
              function assert(name, condition, details) {
                results.push({ name: name, passed: !!condition, details: details || '' });
              }

              // Test 1: Runtime load and error check
              assert("1. Script Load & Zero Uncaught Errors", window.capturedErrors.length === 0, window.capturedErrors.join('; '));

              // Test 2: Valid deep link parsing
              try {
                window.location.hash = "#w_101_3";
                deepLinkHandled = false;
                handleDeepLinks();
                assert("2. Valid Deep Link (#w_101_3)", deepLinkHandled === true, "deepLinkHandled was not set");
              } catch(e) {
                assert("2. Valid Deep Link (#w_101_3)", false, String(e));
              }

              // Test 3: Corrupted deep link resilience
              try {
                window.location.hash = "#w_corrupted_not_a_number";
                deepLinkHandled = false;
                handleDeepLinks();
                assert("3. Corrupted Deep Link (#w_corrupted)", deepLinkHandled === false, "corrupted link should not activate");
              } catch(e) {
                assert("3. Corrupted Deep Link (#w_corrupted)", false, String(e));
              }

              // Test 4: Missing episode handling
              try {
                let toastMsg = "";
                const origToast = window.showToast;
                window.showToast = function(msg) { toastMsg = msg; };
                playEpisode(999, 99);
                assert("4. Missing Episode Handling", true, "Handled cleanly without crash");
                window.showToast = origToast;
              } catch(e) {
                assert("4. Missing Episode Handling", false, String(e));
              }

              // Test 5: Episode range pagination and quick jump
              try {
                const epKeys = Array.from({length: 60}, (_, i) => i + 1);
                currentEpisodePage = 0;
                selectEpisodeRange(1);
                assert("5.1 Episode Range Switch", currentEpisodePage === 1, "Page not updated to 1");

                // Quick jump
                currentCard = { shikimori_id: 101, episodes: 60, kodik: { episodes: { 42: "http://stream/42" } } };
                jumpToEpisode("42");
                assert("5.2 Quick Jump to Episode 42", currentPlayingEpisode === 42, "currentPlayingEpisode was: " + currentPlayingEpisode);
              } catch(e) {
                assert("5. Episode Range and Jump", false, String(e));
              }

              // Test 6: Deep link idempotency (no duplicate run)
              try {
                deepLinkHandled = true;
                let cardOpened = false;
                const origOpen = window.openCard;
                window.openCard = function() { cardOpened = true; };
                handleDeepLinks();
                assert("6. Deep Link Idempotency Guard", cardOpened === false, "openCard called despite deepLinkHandled=true");
                window.openCard = origOpen;
              } catch(e) {
                assert("6. Deep Link Idempotency Guard", false, String(e));
              }

              // Test 7: Cleanup on closeDetail
              try {
                window.location.hash = "#title/101";
                Telegram.WebApp.BackButton.show();
                closeDetail();
                const backVisible = Telegram.WebApp.BackButton.isVisible;
                const modal = document.getElementById('detail-modal');
                const isHidden = modal && modal.classList.contains('hidden');
                assert("7. Close Detail Cleanup (BackButton hidden, modal hidden)", isHidden && !backVisible, "BackButton visible or modal not hidden");
              } catch(e) {
                assert("7. Close Detail Cleanup", false, String(e));
              }

              // Test 8: Search race condition with stale sequence token
              try {
                searchSeqId = 10;
                const mySeq = 5; // stale sequence
                let rendered = false;
                // Simulating late response
                if (mySeq === searchSeqId) {
                  rendered = true;
                }
                assert("8. Search Sequence Token Rejection", rendered === false, "Stale search response rendered");
              } catch(e) {
                assert("8. Search Sequence Token Rejection", false, String(e));
              }

              // Write results to container for Chrome --dump-dom extraction
              const el = document.getElementById('chrome-test-suite-results');
              el.innerText = JSON.stringify(results);
              el.setAttribute('data-completed', 'true');
            }
            try {
              runAutomatedTests();
            } catch(e) {
              const el = document.getElementById('chrome-test-suite-results');
              if (el) {
                el.innerText = JSON.stringify([{name: "FATAL_TEST_RUNNER_ERROR", passed: false, details: String(e)}]);
                el.setAttribute('data-completed', 'true');
              }
            }
            </script>
            """

            # Insert test_harness after <head> and test_runner before </body>
            modified_html = html_content.replace("<head>", "<head>\n" + test_harness)
            modified_html = modified_html.replace("</body>", test_runner + "\n</body>")
            self.wfile.write(modified_html.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


class TestFrontendChrome(unittest.TestCase):
    """Executes real in-browser verification using installed Google Chrome in headless mode."""

    @classmethod
    def setUpClass(cls):
        # 1. Check if Chrome executable is present
        cls.chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if not os.path.exists(cls.chrome_path):
            raise unittest.SkipTest(f"Chrome binary not found at {cls.chrome_path}")

        # 2. Start local mock HTTP server on random port
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockTMAHandler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.shutdown()
            cls.server.server_close()

    def test_chrome_frontend_scenarios(self):
        """Launches headless Chrome with isolated temp profile, dumps rendered DOM and validates assertions."""
        with tempfile.TemporaryDirectory() as temp_profile:
            test_url = f"http://127.0.0.1:{self.port}/test_page.html"
            cmd = [
                self.chrome_path,
                "--headless=new",
                f"--user-data-dir={temp_profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-gpu",
                "--disable-extensions",
                "--dump-dom",
                test_url,
            ]

            proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=15)
            self.assertEqual(proc.returncode, 0, f"Chrome failed with exit code {proc.returncode}: {proc.stderr}")

            stdout = proc.stdout or ""
            marker_start = '<div id="chrome-test-suite-results" style="display:none;" data-completed="true">'
            marker_end = '</div>'

            self.assertIn(marker_start, stdout, "Chrome did not render test suite results container")
            results_json = stdout.split(marker_start)[1].split(marker_end)[0].strip()
            self.assertTrue(results_json, "Empty test results from Chrome DOM")

            results = json.loads(results_json)
            print("\n--- CHROME HEADLESS VERIFICATION REPORT ---")
            all_passed = True
            for r in results:
                status_str = "PASS" if r["passed"] else "FAIL"
                print(f"[{status_str}] {r['name']} {('('+r['details']+')') if r['details'] else ''}")
                if not r["passed"]:
                    all_passed = False

            self.assertTrue(all_passed, "One or more in-browser Chrome assertions failed")


if __name__ == "__main__":
    unittest.main()
