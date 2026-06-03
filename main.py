#!/usr/bin/env python3
"""
Thin entrypoint for Chad Gibiti.

This file delegates startup to run_bot.py so there is one canonical
runtime launcher path to maintain.
"""

from run_bot import main


if __name__ == "__main__":
    main()
