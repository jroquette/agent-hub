"""``hub doctor``: pure rules over a snapshot of the hub (docs/design/hub-doctor.md), no I/O.

The cli reads the hub into a ``DoctorSnapshot``; the rules only look at it and return findings.
"""
