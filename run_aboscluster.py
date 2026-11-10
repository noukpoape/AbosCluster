#!/usr/bin/env python3
"""Lance AbosCluster depuis les sources : python run_aboscluster.py"""
import os
import runpy

runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "aboscluster", "AbosCluster.py"),
               run_name="__main__")
