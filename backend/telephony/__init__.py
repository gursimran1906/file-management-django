"""Record Microsoft Teams phone calls against matters.

Polls the Microsoft Graph PSTN call-log report APIs, matches each external
number to a matter, and — mirroring the Granola integration — auto-creates a
telephone attendance note (or holds the call in a review inbox when it can't be
resolved). Where a Granola note exists for the same conversation, the call and
the note share a single attendance note.
"""
