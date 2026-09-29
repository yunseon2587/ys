"""조회수 기록(snapshot)을 몇 시간마다 자동 실행하도록 등록한다."""
import subprocess
import sys

from .config import ROOT

TASK_NAME = "JPShortsSnapshot"
BAT_PATH = ROOT / "data" / "run_snapshot.bat"


def write_bat():
    """작업 스케줄러가 실행할 배치 파일. 지금 쓰는 파이썬 경로를 그대로 적어 PATH 문제를 피한다."""
    BAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    BAT_PATH.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        f'cd /d "{ROOT}"\r\n'
        f'"{sys.executable}" jp_shorts_finder.py snapshot >> "data\\snapshot.log" 2>&1\r\n',
        encoding="utf-8")
    return BAT_PATH


def windows_create(every_hours):
    bat = write_bat()
    tr = f'"{bat}"' if " " in str(bat) else str(bat)  # 경로에 띄어쓰기가 있을 때만 따옴표
    cmd = ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/SC", "HOURLY", "/MO", str(every_hours),
           "/TR", tr]
    return subprocess.run(cmd, capture_output=True, text=True)


def windows_delete():
    return subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME], capture_output=True, text=True)


def cron_line(every_hours):
    return (f'0 */{every_hours} * * * cd "{ROOT}" && "{sys.executable}" jp_shorts_finder.py snapshot '
            f'>> data/snapshot.log 2>&1')
