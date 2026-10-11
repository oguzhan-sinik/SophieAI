"""Read a case as the bank hands it over: one file, or a folder of documents of several types.

Nothing here knows a bank or a case. A file that cannot be read is skipped with a note that goes into
the trace; it never stops a build."""
from datetime import datetime, timedelta
import html
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib

TEXT = {"", ".md", ".markdown", ".txt", ".text", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".rst", ".log", ".ini", ".toml", ".mmd", ".puml"}
MARKUP = {".html", ".htm", ".xml", ".svg", ".drawio"}
FIRST = ("brief.md", "readme.md")      # the order the organisers give: the brief, then what each file is
MAX_CHARS = 150_000                    # one document; a case's documents are pages, not books
DATA = {".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml"}
MAX_DATA_CHARS = 24_000                # a file of records shows its shape in its first records; the rest is more of the same
MAX_ROWS = 300                         # one sheet
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def decode(data):
    """Text from bytes whose encoding nobody stated: UTF-8, UTF-16 with its mark, then the Turkish Windows page."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    for encoding in ("utf-8-sig", "cp1254"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def markup_text(text):
    """What a person reads in an HTML, XML or drawing file: its text and its labels, one per line."""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    labels = [html.unescape(v) for v in re.findall(r'\b(?:value|label|title|alt)="([^"]{2,})"', text)]
    body = re.sub(r"(?s)<[^>]+>", "\n", text)
    lines = [re.sub(r"<[^>]+>", " ", html.unescape(line)).strip() for line in labels + html.unescape(body).splitlines()]
    seen, kept = set(), []
    for line in lines:
        if line and line not in seen:
            seen.add(line)
            kept.append(line)
    return "\n".join(kept)


def docx_text(path):
    """Paragraphs, headings, list items and tables of a Word document, in reading order."""
    with zipfile.ZipFile(path) as archive:
        body = ET.fromstring(archive.read("word/document.xml")).find(W + "body")

    def paragraph(node):
        parts = []
        for item in node.iter():
            if item.tag == W + "t":
                parts.append(item.text or "")
            elif item.tag == W + "tab":
                parts.append("\t")
            elif item.tag in (W + "br", W + "cr"):
                parts.append("\n")
        text = "".join(parts).strip()
        style = node.find(f"{W}pPr/{W}pStyle")
        name = style.get(W + "val", "") if style is not None else ""
        level = re.search(r"(?i)(?:heading|ba[sş]l[ıi]?k)\s*([1-6])", name)
        if text and level:
            return "#" * int(level.group(1)) + " " + text
        return ("- " + text) if text and node.find(f"{W}pPr/{W}numPr") is not None else text

    lines = []
    for child in body if body is not None else []:
        if child.tag == W + "p":
            lines.append(paragraph(child))
        elif child.tag == W + "tbl":
            for row in child.iter(W + "tr"):
                cells = [" ".join(filter(None, (paragraph(p) for p in cell.iter(W + "p")))) for cell in row.findall(W + "tc")]
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def xlsx_text(path):
    """Every sheet as rows of cells. Dates are written as dates, not as the day count Excel stores."""
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        read = lambda name: ET.fromstring(archive.read(name))
        shared = ["".join(t.text or "" for t in item.iter(S + "t")) for item in read("xl/sharedStrings.xml").findall(S + "si")] if "xl/sharedStrings.xml" in names else []
        dated = []
        if "xl/styles.xml" in names:
            styles = read("xl/styles.xml")
            custom = {f.get("numFmtId"): f.get("formatCode", "") for f in styles.iter(S + "numFmt")}
            formats = styles.find(S + "cellXfs")
            for xf in (list(formats) if formats is not None else []):
                number = xf.get("numFmtId", "0")
                code = re.sub(r'"[^"]*"|\[[^\]]*\]', "", custom.get(number, ""))
                dated.append(number.isdigit() and (14 <= int(number) <= 22 or 27 <= int(number) <= 36 or 45 <= int(number) <= 47 or 50 <= int(number) <= 58) or bool(re.search(r"[dmyDMY]", code)))
        targets = {rel.get("Id"): rel.get("Target", "") for rel in read("xl/_rels/workbook.xml.rels")} if "xl/_rels/workbook.xml.rels" in names else {}
        lines = []
        for sheet in read("xl/workbook.xml").iter(S + "sheet"):
            target = targets.get(sheet.get(R + "id"), "")
            name = target.lstrip("/") if target.startswith("/") else "xl/" + target
            if name not in names:
                continue
            lines.append("## " + (sheet.get("name") or "Sheet"))
            shown = 0
            rows = list(read(name).iter(S + "row"))
            for row in rows:
                cells = {}
                for cell in row.findall(S + "c"):
                    letters = re.match(r"[A-Z]+", cell.get("r", "A"))
                    column = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(letters.group(0)))) if letters else len(cells) + 1
                    kind, value = cell.get("t", ""), cell.find(S + "v")
                    text = (value.text or "") if value is not None else ""
                    if kind == "s" and text.isdigit() and int(text) < len(shared):
                        text = shared[int(text)]
                    elif kind == "inlineStr":
                        text = "".join(t.text or "" for t in cell.iter(S + "t"))
                    elif kind == "b":
                        text = "TRUE" if text == "1" else "FALSE"
                    elif text and kind in ("", "n"):
                        style = cell.get("s", "")
                        if style.isdigit() and int(style) < len(dated) and dated[int(style)]:
                            try:
                                moment = datetime(1899, 12, 30) + timedelta(days=float(text))
                                text = moment.date().isoformat() if float(text) == int(float(text)) else moment.isoformat(sep=" ", timespec="minutes")
                            except (ValueError, OverflowError):
                                pass
                        elif re.fullmatch(r"-?\d+\.0+", text):
                            text = text.split(".")[0]
                    cells[column] = text.strip()
                if any(cells.values()):
                    if shown == MAX_ROWS:
                        lines.append(f"[{len(rows)} rows in this sheet; the first {MAX_ROWS} are shown]")
                        break
                    lines.append(" | ".join(cells.get(i, "") for i in range(1, max(cells) + 1)))
                    shown += 1
            lines.append("")
    return "\n".join(lines).strip()


def pdf_text(path):
    """The text of a PDF: with pypdf when it is installed, otherwise the plain text operators of the page streams.
    The plain reader cannot read fonts with their own character codes; it returns '' rather than noise."""
    try:
        from pypdf import PdfReader
        return "\n\n".join((page.extract_text() or "").strip() for page in PdfReader(str(path)).pages).strip()
    except ImportError:
        pass
    except Exception:
        return ""
    lines = []
    for stream in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", Path(path).read_bytes(), re.S):
        try:
            stream = zlib.decompress(stream)
        except zlib.error:
            pass
        for block in re.findall(rb"BT(.*?)ET", stream, re.S):
            pieces = re.findall(rb"\((?:\\.|[^\\()])*\)", block)
            text = b"".join(re.sub(rb"\\([()\\])", rb"\1", piece[1:-1]) for piece in pieces).decode("latin-1", errors="replace")
            if text.strip():
                lines.append(text.strip())
    text = "\n".join(lines)
    letters = sum(ch.isalpha() or ch.isspace() for ch in text)
    return text if text and letters >= 0.7 * len(text) else ""


def read_document(path):
    """(text, None) for a file that could be read, (None, why not) for one that could not."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix in TEXT:
            text = decode(path.read_bytes())
        elif suffix in MARKUP:
            text = markup_text(decode(path.read_bytes()))
        elif suffix in (".docx", ".docm"):
            text = docx_text(path)
        elif suffix in (".xlsx", ".xlsm"):
            text = xlsx_text(path)
        elif suffix == ".pdf":
            text = pdf_text(path)
            if not text:
                return None, "no text could be read from this PDF (install pypdf for PDFs with embedded fonts; a scanned page has no text at all)"
        else:
            return None, f"a {suffix or 'nameless'} file is not a document this builder reads"
    except (OSError, KeyError, ValueError, ET.ParseError, zipfile.BadZipFile, RecursionError) as exc:
        return None, f"could not be read ({type(exc).__name__}: {str(exc)[:120]})"
    if "\x00" in text[:2000]:
        return None, "binary content"
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None, "empty"
    limit = MAX_DATA_CHARS if suffix in DATA else MAX_CHARS
    if len(text) > limit:
        text = text[:limit] + f"\n[{len(text) - limit} more characters of this {'data file' if suffix in DATA else 'document'} are not shown" + ("; they are more records of the same shape, test data that no design needs in full]" if suffix in DATA else "]")
    return text, None


def load_api(path):
    """The dictionary of a JSON or YAML file, or None when the file is neither."""
    path = Path(path)
    if path.suffix.lower() not in (".json", ".yaml", ".yml"):
        return None
    try:
        text = decode(path.read_bytes())
        if path.suffix.lower() == ".json":
            return json.loads(text)
        import yaml
        # YAML reads a bare date as a date; a contract is plain JSON values.
        return json.loads(json.dumps(yaml.safe_load(text), default=str))
    except Exception:
        return None


def is_api(path):
    """Told apart by content: a brief document may be JSON too (a code list)."""
    document = load_api(path)
    return isinstance(document, dict) and ("openapi" in document or "swagger" in document)


def case_files(folder):
    """The files of a case folder in reading order: the brief, the file that says what each file is, then the rest by name."""
    folder = Path(folder)
    files = [p for p in sorted(folder.rglob("*"), key=lambda p: str(p.relative_to(folder)).lower()) if p.is_file()
             and not any(part.startswith((".", "__MACOSX", "~$")) for part in p.relative_to(folder).parts)]
    rank = lambda p: (FIRST.index(p.name.lower()) if p.name.lower() in FIRST else len(FIRST), len(p.relative_to(folder).parts))
    return sorted(files, key=rank)
