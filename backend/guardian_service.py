import os
import sys
import time
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# UTF-8 Output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from strategy_parser import StrategyManager, DEFAULT_ZAPRET_DIR
from network_tester import NetworkTester
from hosts_manager import HostsManager

try:
    from config_manager import ConfigManager
except ImportError:
    from backend.config_manager import ConfigManager

cfg = ConfigManager()
active_zapret_dir = cfg.get("zapret_dir") or DEFAULT_ZAPRET_DIR

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

strategy_mgr = StrategyManager(active_zapret_dir)
network_tester = NetworkTester(timeout=3.5)
hosts_mgr = HostsManager(active_zapret_dir)

app = FastAPI(title="Zapret Guardian & Master GUI", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory cache for last benchmark results
last_benchmark_results: Dict[str, Any] = {}
auto_benchmark_state: Dict[str, Any] = {
    "isRunning": False,
    "progress": 0,
    "currentStrategy": "",
    "results": [],
    "winner": None,
}


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/api/status")
def get_status():
    proc = strategy_mgr.get_running_process()
    strategies = strategy_mgr.get_all_strategies()
    active_strat = strategy_mgr.detect_active_strategy(strategies) if proc else None
    service_info = strategy_mgr.get_service_status()

    return {
        "status": "online",
        "isRunning": proc is not None,
        "pid": proc["pid"] if proc else None,
        "uptime": proc["uptime"] if proc else 0,
        "activeStrategy": active_strat,
        "service": service_info,
        "zapretDir": strategy_mgr.zapret_dir,
        "totalStrategies": len(strategies),
        "lastTest": last_benchmark_results.get("lastTest"),
    }


@app.get("/api/strategies")
def get_strategies():
    strategies = strategy_mgr.get_all_strategies()
    running_proc = strategy_mgr.get_running_process()
    active_strat = strategy_mgr.detect_active_strategy(strategies) if running_proc else None

    for s in strategies:
        s["isActive"] = (s["filename"] == active_strat)
        s["lastResult"] = last_benchmark_results.get(s["filename"])

    return strategies


@app.post("/api/strategies/activate")
def activate_strategy(payload: Dict[str, Any]):
    filename = payload.get("filename")
    if not filename:
        raise HTTPException(status_code=400, detail="Filename required")

    res = strategy_mgr.start_strategy(filename)
    if not res.get("success"):
        raise HTTPException(status_code=500, detail=res.get("error"))

    return res


@app.post("/api/strategies/stop")
def stop_strategies():
    stopped = strategy_mgr.stop_winws()
    return {"success": True, "stopped": stopped}


@app.post("/api/test-connection")
def run_test():
    report = network_tester.run_full_diagnostic()
    last_benchmark_results["lastTest"] = report

    # If an active strategy is running, associate this result with it
    proc = strategy_mgr.get_running_process()
    if proc:
        strategies = strategy_mgr.get_all_strategies()
        active_strat = strategy_mgr.detect_active_strategy(strategies)
        if active_strat:
            last_benchmark_results[active_strat] = {
                "timestamp": report["timestamp"],
                "score": report["overallScore"],
                "discordScore": report["discord"]["score"],
                "youtubeScore": report["youtube"]["score"],
                "voiceLatency": report["discord"]["voiceStun"]["latency"],
                "ytLatency": report["youtube"]["averageLatency"],
                "verdict": report["verdict"],
            }

    return report


def background_auto_benchmark():
    global auto_benchmark_state
    auto_benchmark_state["isRunning"] = True
    auto_benchmark_state["results"] = []
    auto_benchmark_state["progress"] = 0

    # Top candidate strategies to benchmark
    candidates = [
        "general (ALT).bat",
        "general (ALT4).bat",
        "general (ALT11).bat",
        "general (FAKE TLS AUTO ALT).bat",
        "general (ALT2).bat",
        "general.bat",
    ]

    # Filter to existing
    available = [s["filename"] for s in strategy_mgr.get_all_strategies()]
    to_test = [c for c in candidates if c in available]
    if not to_test:
        to_test = available[:5]

    tested_results = []
    total = len(to_test)

    for idx, strat_name in enumerate(to_test):
        auto_benchmark_state["currentStrategy"] = strat_name
        auto_benchmark_state["progress"] = int((idx / total) * 100)

        # Switch strategy
        strategy_mgr.start_strategy(strat_name)
        # Wait 2.0 seconds for WinDivert filter to settle
        time.sleep(2.0)

        # Run test
        diag = network_tester.run_full_diagnostic()
        score = diag["overallScore"]
        voice_ok = diag["discord"]["voiceStun"]["status"] == "ok"
        voice_latency = diag["discord"]["voiceStun"]["latency"]
        yt_latency = diag["youtube"]["averageLatency"]

        result_item = {
            "strategy": strat_name,
            "overallScore": score,
            "discordScore": diag["discord"]["score"],
            "youtubeScore": diag["youtube"]["score"],
            "voiceOk": voice_ok,
            "voiceLatency": voice_latency,
            "ytLatency": yt_latency,
            "verdict": diag["verdict"],
            "verdictText": diag["verdictText"],
        }
        tested_results.append(result_item)
        last_benchmark_results[strat_name] = result_item

    # Pick winner: highest score, with working voice preferred, then lowest latency
    tested_results.sort(
        key=lambda r: (1 if r["voiceOk"] else 0, r["overallScore"], -r["voiceLatency"]),
        reverse=True,
    )
    winner = tested_results[0] if tested_results else None

    # Automatically activate the winner!
    if winner:
        strategy_mgr.start_strategy(winner["strategy"])

    auto_benchmark_state["isRunning"] = False
    auto_benchmark_state["progress"] = 100
    auto_benchmark_state["results"] = tested_results
    auto_benchmark_state["winner"] = winner


@app.post("/api/benchmark-auto")
def start_auto_benchmark(background_tasks: BackgroundTasks):
    if auto_benchmark_state["isRunning"]:
        return {"success": False, "message": "Бенчмарк уже выполняется"}

    background_tasks.add_task(background_auto_benchmark)
    return {"success": True, "message": "Авто-бенчмарк запущен"}


@app.get("/api/benchmark-auto/status")
def get_auto_benchmark_status():
    return auto_benchmark_state


@app.post("/api/service/install")
def install_service_endpoint(payload: Dict[str, Any]):
    filename = payload.get("filename")
    if not filename:
        raise HTTPException(status_code=400, detail="Filename required")
    res = strategy_mgr.install_service(filename)
    if not res.get("success"):
        raise HTTPException(status_code=500, detail=res.get("error"))
    return res


@app.post("/api/service/uninstall")
def uninstall_service_endpoint():
    res = strategy_mgr.uninstall_service()
    return res


@app.get("/api/lists")
def get_user_lists():
    return {
        "generalUser": hosts_mgr.read_domains("list-general-user"),
        "excludeUser": hosts_mgr.read_domains("list-exclude-user"),
        "presets": hosts_mgr.get_presets_info(),
    }


@app.post("/api/lists/save")
def save_user_list(payload: Dict[str, Any]):
    list_name = payload.get("listName", "list-general-user")
    domains = payload.get("domains", [])
    ok = hosts_mgr.write_domains(domains, list_name)
    return {"success": ok}


@app.post("/api/lists/apply-preset")
def apply_preset_endpoint(payload: Dict[str, Any]):
    preset_key = payload.get("presetKey")
    list_name = payload.get("listName", "list-general-user")
    updated = hosts_mgr.apply_preset(preset_key, list_name)
    return {"success": True, "domains": updated}


@app.post("/api/open-zapret-folder")
def open_zapret_folder():
    try:
        os.startfile(strategy_mgr.zapret_dir)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    port = 5200
    print(f"\n🛡️ Zapret Guardian Server starting on http://localhost:{port} ...\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
