"""synthgen — synthetic ground-truth drawing pair generator (research R12).

Generates two vector-PDF revisions of a parameterized sheet plus an
answer-key JSON describing every injected change, so pipeline phases can be
validated against known deltas (Constitution V).
"""

from synthgen.pairs import make_pair  # noqa: F401
