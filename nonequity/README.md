# nonequity/ — EXPERIMENTAL (NO-GO)

Non-equity futures (gold GC, crude CL) continuous-bar research harness.

**Status:** NO-GO — standalone experiment, not wired into production. Universe too small, Databento dependency not provisioned.

`_core.py` and `fetch.py` are COPY of `futures/_validated_core.py` / `global_index/fetch.py` primitives (sync manually if canonical changes).

Production futures engine is in `futures/_validated_core.py`.
