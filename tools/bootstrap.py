#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容旧引用，请改用 tools/entry.py。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entry import Main

if __name__ == "__main__":
    Main()
