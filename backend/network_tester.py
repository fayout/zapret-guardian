import socket
import ssl
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any

class NetworkTester:
    def __init__(self, timeout: float = 3.5):
        self.timeout = timeout
        self.ssl_context = ssl.create_default_context()

    def check_http_endpoint(self, name: str, url: str, expected_codes=(200, 204, 301, 302)) -> Dict[str, Any]:
        """Performs HTTPS GET request and measures Time To First Byte (TTFB) in ms."""
        t0 = time.time()
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl_context) as res:
                elapsed_ms = round((time.time() - t0) * 1000, 1)
                ok = res.status in expected_codes
                return {
                    "name": name,
                    "url": url,
                    "status": "ok" if ok else "error",
                    "code": res.status,
                    "latency": elapsed_ms,
                    "error": None,
                }
        except urllib.error.HTTPError as e:
            elapsed_ms = round((time.time() - t0) * 1000, 1)
            ok = e.code in expected_codes
            return {
                "name": name,
                "url": url,
                "status": "ok" if ok else "error",
                "code": e.code,
                "latency": elapsed_ms,
                "error": None if ok else f"HTTP {e.code}",
            }
        except Exception as e:
            elapsed_ms = round((time.time() - t0) * 1000, 1)
            return {
                "name": name,
                "url": url,
                "status": "fail",
                "code": None,
                "latency": elapsed_ms,
                "error": str(e),
            }

    def check_stun_udp(self, host: str = "stun.l.google.com", port: int = 19302) -> Dict[str, Any]:
        """Sends a standard RFC 5389 STUN Binding Request over UDP to test Discord Voice/WebRTC bypass."""
        t0 = time.time()
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)
            # STUN Binding Request (Type 0x0001, Length 0, Magic Cookie 0x2112A442, 12-byte Transaction ID)
            tx_id = b"\x47\x75\x61\x72\x64\x69\x61\x6e\x54\x65\x73\x74"
            packet = b"\x00\x01\x00\x00\x21\x12\xa4\x42" + tx_id
            sock.sendto(packet, (host, port))
            resp, addr = sock.recvfrom(1024)
            elapsed_ms = round((time.time() - t0) * 1000, 1)

            # Check if response is STUN Binding Success (0x0101)
            if len(resp) >= 20 and resp[:2] == b"\x01\x01":
                return {
                    "name": "Discord Voice STUN (UDP)",
                    "status": "ok",
                    "latency": elapsed_ms,
                    "details": f"UDP Response {len(resp)}B from {addr[0]}",
                    "error": None,
                }
            else:
                return {
                    "name": "Discord Voice STUN (UDP)",
                    "status": "partial",
                    "latency": elapsed_ms,
                    "details": f"Unexpected STUN opcode: {resp[:2].hex()}",
                    "error": None,
                }
        except socket.timeout:
            return {
                "name": "Discord Voice STUN (UDP)",
                "status": "fail",
                "latency": round(self.timeout * 1000, 1),
                "details": "UDP Timeout (Packets dropped by DPI)",
                "error": "Timeout",
            }
        except Exception as e:
            return {
                "name": "Discord Voice STUN (UDP)",
                "status": "fail",
                "latency": round((time.time() - t0) * 1000, 1),
                "details": str(e),
                "error": str(e),
            }
        finally:
            if sock:
                sock.close()

    def run_full_diagnostic(self) -> Dict[str, Any]:
        """Runs all checks in parallel and compiles high-level health report."""
        targets = [
            ("discord_api", "https://discord.com/api/v10/gateway", (200,)),
            ("discord_web", "https://discord.com", (200, 301, 302)),
            ("discord_cdn", "https://cdn.discordapp.com/icons/586020206741487640/25d97d09559c7379d7ebfa674b8fb492.png", (200,)),
            ("youtube_web", "https://www.youtube.com", (200, 301, 302)),
            ("youtube_cdn", "https://redirector.googlevideo.com/report_mapping", (200,)),
            ("youtube_img", "https://i.ytimg.com/generate_204", (200, 204)),
            ("cloudflare_dns", "https://1.1.1.1", (200, 301, 302)),
        ]

        results = {}
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(self.check_http_endpoint, key, url, codes): key
                for key, url, codes in targets
            }
            stun_future = executor.submit(self.check_stun_udp)

            for f in futures:
                key = futures[f]
                results[key] = f.result()

            results["discord_stun"] = stun_future.result()

        # Calculate Scores
        discord_ok_count = (
            (1 if results["discord_api"]["status"] == "ok" else 0) +
            (1 if results["discord_web"]["status"] == "ok" else 0) +
            (1 if results["discord_stun"]["status"] == "ok" else 0)
        )
        discord_score = int((discord_ok_count / 3) * 100)

        yt_ok_count = (
            (1 if results["youtube_web"]["status"] == "ok" else 0) +
            (1 if results["youtube_cdn"]["status"] == "ok" else 0) +
            (1 if results["youtube_img"]["status"] == "ok" else 0)
        )
        yt_score = int((yt_ok_count / 3) * 100)

        overall_score = int((discord_score + yt_score) / 2)

        if overall_score >= 85 and results["discord_stun"]["status"] == "ok":
            verdict = "perfect"
            verdict_text = "Отлично! Discord Voice и YouTube 4K работают без сбоев"
        elif discord_score >= 60 and yt_score >= 60:
            verdict = "good"
            verdict_text = "Хорошо. Сервисы доступны, возможны микро-задержки"
        elif yt_score >= 60:
            verdict = "yt_only"
            verdict_text = "YouTube работает, но Discord Voice или Gateway блокируются"
        elif discord_score >= 60:
            verdict = "discord_only"
            verdict_text = "Discord работает, но видеопоток YouTube блокируется"
        else:
            verdict = "blocked"
            verdict_text = "Блокировка активна! Рекомендуется сменить стратегию Zapret"

        return {
            "timestamp": time.time(),
            "overallScore": overall_score,
            "verdict": verdict,
            "verdictText": verdict_text,
            "discord": {
                "score": discord_score,
                "api": results["discord_api"],
                "web": results["discord_web"],
                "cdn": results["discord_cdn"],
                "voiceStun": results["discord_stun"],
                "averageLatency": round(
                    (results["discord_api"]["latency"] + results["discord_stun"]["latency"]) / 2, 1
                ),
            },
            "youtube": {
                "score": yt_score,
                "web": results["youtube_web"],
                "cdn": results["youtube_cdn"],
                "img": results["youtube_img"],
                "averageLatency": round(
                    (results["youtube_web"]["latency"] + results["youtube_cdn"]["latency"]) / 2, 1
                ),
            },
            "raw": results,
        }
