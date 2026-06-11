"""Integration with Granola (granola.ai) AI meeting notes.

Fee earners record call/meeting notes in Granola. A scheduled job pulls newly
summarised notes from Granola's official REST API and turns them into
``MatterAttendanceNotes`` against the right matter. Notes whose matter cannot be
auto-resolved land in a central review inbox.

Key concepts:

* The matter is encoded in the Granola note *title* using a template understood
  by :func:`backend.granola.parse.parse_title`, e.g. ``[A12345] Call with client``
  or ``[A12345 NC] Internal catch-up`` (``NC`` = not charged).
* A single central API key (env ``GRANOLA_API_KEY`` or the ``GranolaConfig`` row)
  is used for the whole team.
"""
