import sys
import os

sys.path.append(os.getcwd())

from agents.hephaestus.agent import run_hephaestus_task

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_hephaestus.py \"Implement SCRUM-24\"")
    else:
        run_hephaestus_task(sys.argv[1])