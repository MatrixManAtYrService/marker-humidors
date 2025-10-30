from __future__ import annotations

from humidor.server.ucm import parse_records

# Captured from a real list run against Unison Cloud (Nov 2026), record prefix since renamed.
REAL_LIST_STDOUT = (
    "\n⚙️   Processing stanza 1 of 2.\n"
    "                                                                                \n\n"
    "⚙️   Processing stanza 2 of 2.HUMIDOR\tservice\thello-world\t1e9fee62-30c4-4b61-ba91-197205838ee3\t"
    "ozrpvknrtnqg2y4ehmezooyzn6zcntuffyoctkylof7mthnmwv5a\tInstant +1762796643 642980000\n\n"
    "✔️   Completed transcript.\n"
)

# The transcript echoes program source, where tabs are the two characters \t.
ECHOED_SOURCE = 'printLine ("HUMIDOR\\tservice\\t" ++ n)\n'


def test_records_glued_to_progress_text_are_found():
    assert parse_records(REAL_LIST_STDOUT) == [
        [
            "service",
            "hello-world",
            "1e9fee62-30c4-4b61-ba91-197205838ee3",
            "ozrpvknrtnqg2y4ehmezooyzn6zcntuffyoctkylof7mthnmwv5a",
            "Instant +1762796643 642980000",
        ]
    ]


def test_echoed_source_is_not_a_record_and_duplicates_collapse():
    assert parse_records(ECHOED_SOURCE + REAL_LIST_STDOUT + REAL_LIST_STDOUT) == parse_records(REAL_LIST_STDOUT)
