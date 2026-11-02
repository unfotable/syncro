#!/usr/bin/env python3
"""
Syncro — the live ID network, served entirely by Python.

    pip install -r requirements.txt
    python app.py
    → open http://127.0.0.1:8787

Make an ID, lock it with a password, upload a picture — every profile, every
asset and every action is saved by this server, in plain SQLite, forever
yours to export.
"""

from syncro.server import main

if __name__ == "__main__":
    main()
