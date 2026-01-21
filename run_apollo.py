import sys
import os

sys.path.append(os.getcwd())

from agents.apollo.agent import run_apollo_task

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_apollo.py \"Explain how the payment logic works\"")
    else:
        run_apollo_task(sys.argv[1])