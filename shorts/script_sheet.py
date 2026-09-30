"""대본 작성 엑셀 시트 만들기 (수정 전 / 수정 후, 타임라인·화자·원문·번역 대사 또는 나레이션)."""
import re
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from .config import OUTPUT_DIR
from .trending import enrich

ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})|^([A-Za-z0-9_-]{11})$")

# 기승전결 구간과 미리 만들어 둘 줄 수
SECTIONS = [("기 (0~3초 후킹)", 2), ("승 (몰입·갈등)", 5), ("전 (사이다·반전)", 5), ("결 (마무리·댓글 유도)", 3)]
EXTRA_ROWS = 10
COLS = ["구간", "타임라인", "화자", "원문", "번역 대사 or 나레이션"]
WIDTHS = [18, 11, 10, 40, 45]

RED, BLUE = "E53935", "1E88E5"
HEAD_FILL = PatternFill("solid", fgColor="FFF2CC")
COL_FILL = PatternFill("solid", fgColor="D9EAD3")
SECTION_FILL = {"기": "FDE2E2", "승": "FFF4D6", "전": "DDEBFF", "결": "E6F4EA"}
THIN = Side(style="thin", color="BBBBBB")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")

GUIDE = [
    ("구간", "할 일", "예시 방향"),
    ("기 (0~3초)", "첫 화면 문구로 스와이프를 막는다. 선입견·의외의 상황·도발적 질문.",
     "\"한국 ○○을 무시하던 외국인이…\" / \"○천원에 이게 다 나온다고?\""),
    ("승", "긴장감·궁금증을 쌓는다. 문화 차이, 외국인의 의심, 한국인의 무심한 반응.",
     "외국인은 수상하게 봤지만… / 주문도 안 했는데 나온 서비스"),
    ("전", "기다리던 반응이 터지는 구간. 감탄, 180도 태도 변화, 압도적인 비교.",
     "한 입 먹자마자 표정이 바뀜 / 한 달 걸릴 일이 10분 만에"),
    ("결", "여운 + 자부심으로 정리하고 댓글을 부른다.",
     "\"여러분도 이런 경험 있으신가요?\""),
    ("", "", ""),
    ("나레이션 팁", "① 행동 설명보다 감정을 말한다  ② 한국인에겐 당연한 것에 외국인이 놀라는 '온도 차'를 살린다  "
                   "③ 결론은 맛·기술·서비스·정 중 하나로 모은다", ""),
    ("", "", ""),
    ("체크리스트", "□ 후킹 제목 2줄 (윗줄 흰색 / 아랫줄 노란색 강조)", ""),
    ("", "□ 원작자 사용 허락 받기 (출처 표기만으로는 저작권 허락이 되지 않음)", ""),
    ("", "□ 영상 하단에 '출처 - 채널명' 표기", ""),
    ("", "□ 같은 소스를 일본 채널에도 쓸 거면 check 명령으로 일본에 이미 있는지 확인", ""),
]


def parse_video_id(text):
    m = ID_RE.search(text.strip())
    if not m:
        return None
    return m.group(1) or m.group(2)


def fmt_duration(sec):
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def _block(ws, col0, label, color, title):
    """col0부터 5칸짜리 '수정 전' 또는 '수정 후' 블록을 그린다. 표가 시작하는 행 번호를 돌려준다."""
    top = 9
    ws.merge_cells(start_row=top, start_column=col0, end_row=top, end_column=col0 + 4)
    c = ws.cell(top, col0, label)
    c.fill, c.font, c.alignment = PatternFill("solid", fgColor=color), Font(bold=True, color="FFFFFF"), \
        Alignment(horizontal="center")
    for i, (name, value) in enumerate([("제목", title), ("소제목", "")], start=1):
        ws.cell(top + i, col0, name).fill = HEAD_FILL
        ws.cell(top + i, col0).font = Font(bold=True)
        ws.merge_cells(start_row=top + i, start_column=col0 + 1, end_row=top + i, end_column=col0 + 4)
        ws.cell(top + i, col0 + 1, value).alignment = WRAP
    for j, name in enumerate(COLS):
        c = ws.cell(top + 3, col0 + j, name)
        c.fill, c.font, c.border, c.alignment = COL_FILL, Font(bold=True), BOX, Alignment(horizontal="center")
    row = top + 4
    for name, n in SECTIONS:
        for k in range(n):
            c = ws.cell(row, col0, name if k == 0 else "")
            c.fill = PatternFill("solid", fgColor=SECTION_FILL[name[0]])
            for j in range(5):
                ws.cell(row, col0 + j).border = BOX
                ws.cell(row, col0 + j).alignment = WRAP
            row += 1
    for _ in range(EXTRA_ROWS):
        for j in range(5):
            ws.cell(row, col0 + j).border = BOX
        row += 1


def build_workbook(v):
    wb = Workbook()
    ws = wb.active
    ws.title = "대본"
    info = [
        ("원본 영상", v["url"]),
        ("원본 채널", f"{v['channel']}  (https://youtube.com/channel/{v['channel_id']})"),
        ("길이 · 조회수", f"{fmt_duration(v['sec'])} · {v['views']:,}회 · 구독자 {v['subs']:,}명"),
        ("출처 표기", f"출처 - {v['channel']}"),
        ("사용 허락", "□ 받음   (날짜:            방법: 댓글 / 이메일 / DM)"),
        ("만든 날짜", datetime.now().strftime("%Y-%m-%d")),
    ]
    ws.cell(1, 1, "영상 정보").font = Font(bold=True, size=13)
    for i, (k, val) in enumerate(info, start=2):
        ws.cell(i, 1, k).font = Font(bold=True)
        ws.merge_cells(start_row=i, start_column=2, end_row=i, end_column=11)
        ws.cell(i, 2, val)
    _block(ws, 1, "수정 전", RED, v["title"])
    _block(ws, 7, "수정 후", BLUE, "(후킹 제목 2줄: 윗줄 흰색 / 아랫줄 노란색 강조 — 이 문구를 지우고 쓰세요)")
    for j, w in enumerate(WIDTHS):
        ws.column_dimensions[chr(ord("A") + j)].width = w
        ws.column_dimensions[chr(ord("G") + j)].width = w
    ws.column_dimensions["F"].width = 3
    ws.freeze_panes = "A13"

    g = wb.create_sheet("작성 가이드")
    for i, row in enumerate(GUIDE, start=1):
        for j, val in enumerate(row, start=1):
            c = g.cell(i, j, val)
            c.alignment = WRAP
            if i == 1 or j == 1:
                c.font = Font(bold=True)
    g.column_dimensions["A"].width, g.column_dimensions["B"].width, g.column_dimensions["C"].width = 14, 70, 50
    return wb


def make_sheets(video_refs):
    """영상 URL/ID 목록 → 엑셀 파일 경로 목록. 영상 정보 조회에 50개당 약 2유닛."""
    ids, bad = [], []
    for ref in video_refs:
        vid = parse_video_id(ref)
        (ids if vid else bad).append(vid or ref)
    videos = {r["video_id"]: r for r in enrich(ids, include_long=True)}
    OUTPUT_DIR.mkdir(exist_ok=True)
    made, missing = [], [i for i in ids if i not in videos] + bad
    for vid in ids:
        if vid not in videos:
            continue
        path = OUTPUT_DIR / f"script_{datetime.now():%Y%m%d}_{vid}.xlsx"
        build_workbook(videos[vid]).save(path)
        made.append(path)
    return made, missing
