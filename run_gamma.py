import sys
import os

sys.path.append(os.getcwd())

from agents.artemis.agent import run_qa_agent_task

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_gamma.py \"Task Description\"")
    else:
        run_qa_agent_task(sys.argv[1])