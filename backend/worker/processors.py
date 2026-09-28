"""CSV processors: bytes in, result CSV bytes out. Pure functions, no DB or storage access.

Row-level problems are reported in the result (the job still completes). Problems that make the
whole file unusable raise DataError, which fails the job without retrying.
"""
from collections.abc import Callable
import csv
from dataclasses import dataclass
import io
import re


class DataError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Result:
    rows_in: int
    rows_out: int
    error_rows: int
    output: bytes
    summary: str


def read_csv(data: bytes) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Returns the header and (line number, row) pairs, skipping blank lines."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DataError("INVALID_CSV", "UTF-8로 읽을 수 없는 파일입니다.")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    rows = []
    try:
        for row in reader:
            if any(cell.strip() for cell in row):
                rows.append((reader.line_num, row))
    except csv.Error as error:
        raise DataError("INVALID_CSV", f"CSV 구문 오류 ({reader.line_num}행): {error}")
    if not rows:
        raise DataError("EMPTY_FILE", "헤더가 없는 빈 파일입니다.")
    (_, header), data_rows = rows[0], rows[1:]
    header = [name.strip() for name in header]
    for index, name in enumerate(header, 1):
        if not name:
            raise DataError("SCHEMA_MISMATCH", f"{index}번째 열의 이름이 비어 있습니다.")
    duplicates = sorted({name for name in header if header.count(name) > 1})
    if duplicates:
        raise DataError("SCHEMA_MISMATCH", f"중복된 열 이름: {', '.join(duplicates)}")
    if not data_rows:
        raise DataError("EMPTY_FILE", "헤더만 있고 데이터 행이 없습니다.")
    return header, data_rows


def write_csv(header: list[str], rows) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    # BOM so Excel opens Korean text correctly.
    return buffer.getvalue().encode("utf-8-sig")


def validate(data: bytes) -> Result:
    header, rows = read_csv(data)
    problems, bad_lines = [], set()
    for line, row in rows:
        if len(row) != len(header):
            problems.append((line, "", f"열 개수 불일치: {len(row)}개 (헤더 {len(header)}개)"))
            bad_lines.add(line)
            continue
        for column, value in zip(header, row):
            if not value.strip():
                problems.append((line, column, "빈 값"))
                bad_lines.add(line)
    return Result(len(rows), len(rows) - len(bad_lines), len(bad_lines),
                  write_csv(["line", "column", "error"], problems),
                  f"{len(rows)}행 검사, 오류 행 {len(bad_lines)}개")


def cleanse(data: bytes) -> Result:
    header, rows = read_csv(data)
    kept, seen = [], set()
    malformed = duplicates = 0
    for _, row in rows:
        if len(row) != len(header):
            malformed += 1
            continue
        cleaned = tuple(cell.strip() for cell in row)
        if cleaned in seen:
            duplicates += 1
            continue
        seen.add(cleaned)
        kept.append(cleaned)
    return Result(len(rows), len(kept), malformed, write_csv(header, kept),
                  f"{len(rows)}행 중 {len(kept)}행 유지 (중복 {duplicates}행, 형식 오류 {malformed}행 제거)")


NUMBER_WITH_COMMAS = re.compile(r"[+-]?\d{1,3}(,\d{3})+(\.\d+)?")


def to_snake_case(name: str) -> str:
    return re.sub(r"[^\w]+", "_", name.strip().lower()).strip("_") or "column"


def transform(data: bytes) -> Result:
    header, rows = read_csv(data)
    names: list[str] = []
    for name in map(to_snake_case, header):
        candidate, suffix = name, 2
        while candidate in names:
            candidate, suffix = f"{name}_{suffix}", suffix + 1
        names.append(candidate)
    out, malformed, numbers = [], 0, 0
    for _, row in rows:
        if len(row) != len(header):
            malformed += 1
            continue
        cells = []
        for cell in row:
            cell = cell.strip()
            if NUMBER_WITH_COMMAS.fullmatch(cell):
                cell, numbers = cell.replace(",", ""), numbers + 1
            cells.append(cell)
        out.append(cells)
    return Result(len(rows), len(out), malformed, write_csv(names, out),
                  f"열 이름 {len(names)}개 표준화, 숫자 {numbers}개 변환, 형식 오류 {malformed}행 제외")


def parse_number(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def aggregate(data: bytes) -> Result:
    """Per-column profile: counts for every column, min/max/sum/mean for fully numeric ones."""
    header, rows = read_csv(data)
    valid = [row for _, row in rows if len(row) == len(header)]
    stats = []
    for index, column in enumerate(header):
        values = [row[index].strip() for row in valid]
        filled = [v for v in values if v]
        numbers = [parse_number(v) for v in filled]
        numeric = bool(filled) and all(n is not None for n in numbers)
        line = [column, len(filled), len(values) - len(filled), len(set(filled)), "yes" if numeric else "no"]
        if numeric:
            total = sum(numbers)
            line += [f"{min(numbers):g}", f"{max(numbers):g}", f"{total:g}", f"{total / len(numbers):.4g}"]
        else:
            line += ["", "", "", ""]
        stats.append(line)
    return Result(len(rows), len(stats), len(rows) - len(valid),
                  write_csv(["column", "non_empty", "empty", "distinct", "numeric", "min", "max", "sum", "mean"], stats),
                  f"{len(valid)}행 기준 {len(header)}개 열 통계, 형식 오류 {len(rows) - len(valid)}행 제외")


PROCESSORS: dict[str, Callable[[bytes], Result]] = {
    "validation": validate,
    "cleansing": cleanse,
    "transformation": transform,
    "aggregation": aggregate,
}
