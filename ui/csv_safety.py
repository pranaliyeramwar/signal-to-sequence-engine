"""Spreadsheet formula-injection protection for CSV downloads.

Applied only when a CSV file is written. The text held and shown inside the application is never changed.

A text cell is neutralised by prefixing a single quote (') when, after skipping any leading whitespace
or invisible/control characters, it starts with a formula trigger: = + - @ (including full-width forms).
Cells that start with a tab or carriage return are also neutralised. The original text follows the quote
unchanged, so nothing is lost. Non-text values (numbers, None) are written as they are.
"""

import csv
import io
import unicodedata

FORMULA_TRIGGERS = frozenset("=+-@＝＋－＠")   # ASCII and full-width = + - @
DANGEROUS_FIRST_CHARACTERS = frozenset("\t\r")
NEUTRALISING_PREFIX = "'"


def is_skippable(character):
    """Whitespace, control (Cc) and format (Cf, e.g. zero-width) characters a spreadsheet may ignore."""
    return character.isspace() or unicodedata.category(character) in ("Cc", "Cf")


def is_dangerous(value):
    if not isinstance(value, str) or not value:
        return False
    if value[0] in DANGEROUS_FIRST_CHARACTERS:
        return True
    for character in value:
        if not is_skippable(character):
            return character in FORMULA_TRIGGERS
    return False


def neutralise_cell(value):
    return NEUTRALISING_PREFIX + value if is_dangerous(value) else value


def neutralise_row(row):
    return {key: neutralise_cell(value) for key, value in row.items()}


def safe_csv_bytes(rows, columns):
    """UTF-8 CSV with every text cell neutralised. The rows passed in are not modified."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(neutralise_row(row) for row in rows)
    return buffer.getvalue().encode("utf-8")
