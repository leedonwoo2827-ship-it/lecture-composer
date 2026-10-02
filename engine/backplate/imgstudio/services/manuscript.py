"""원고 파일에서 텍스트 추출 (표준 라이브러리만 사용, 추가 의존성 없음).

지원: .txt/.md/.csv/.json/.log (평문), .docx, .hwpx, .pptx (zip+xml).
미지원(.pdf/.hwp 등)은 안내 메시지 반환 → 사용자가 텍스트로 붙여넣도록.
"""
from __future__ import annotations

import html
import io
import re
import zipfile

MAX_CHARS = 20000   # 토큰 폭주 방지 상한
_PLAIN = {"txt", "md", "markdown", "csv", "json", "log", "text"}


def _strip_xml(xml: str, para_tag: str) -> str:
    """문단 닫는 태그를 줄바꿈으로, 나머지 태그 제거 후 엔티티 복원."""
    xml = re.sub(rf"</{para_tag}>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    return html.unescape(text)


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    return _strip_xml(xml, "w:p")


def _hwpx_text(data: bytes) -> str:
    out: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.startswith("Contents/") and n.endswith(".xml")]
        sections = [n for n in names if "section" in n.lower()] or names
        for n in sorted(sections):
            xml = z.read(n).decode("utf-8", "ignore")
            out.append(_strip_xml(xml, "hp:p"))
    return "\n".join(out)


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader  # 지연 임포트 (미설치 시 안내 메시지로 폴백)
    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _pptx_text(data: bytes) -> str:
    out: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        slides = sorted(n for n in z.namelist()
                        if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
        for n in slides:
            xml = z.read(n).decode("utf-8", "ignore")
            xml = xml.replace("</a:p>", "\n")
            out.append(html.unescape(re.sub(r"<[^>]+>", "", xml)))
    return "\n".join(out)


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """(추출 텍스트, 안내메시지) 반환. 성공 시 메시지는 빈 문자열."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    try:
        if ext in _PLAIN:
            for enc in ("utf-8", "cp949", "euc-kr"):
                try:
                    return _clean(data.decode(enc)), ""
                except UnicodeDecodeError:
                    continue
            return _clean(data.decode("utf-8", "ignore")), ""
        if ext == "pdf":
            try:
                return _clean(_pdf_text(data)), ""
            except ModuleNotFoundError:
                return "", "PDF 추출 라이브러리(pypdf)가 설치되지 않았습니다. setup.bat을 다시 실행하세요."
        if ext == "docx":
            return _clean(_docx_text(data)), ""
        if ext == "hwpx":
            return _clean(_hwpx_text(data)), ""
        if ext == "pptx":
            # pptx는 도형/순서가 흩어져 best-effort. 결과가 부실하면 메모란 사용 권장.
            return _clean(_pptx_text(data)), ""
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        return "", f"파일을 읽지 못했습니다: {exc}"
    return "", (
        f"'{ext or '알 수 없음'}' 형식은 아직 자동 추출을 지원하지 않습니다. "
        ".txt/.md/.docx/.hwpx/.pptx 로 올리거나, 원고 내용을 메모란에 붙여 주세요."
    )


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text
