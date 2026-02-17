import sys
import os
import core.network_fix

# 1. Setup Path
sys.path.append(os.getcwd())

# 2. ✅ Force Identity BEFORE importing agent
from core.config import settings
settings.CURRENT_AGENT_NAME = "Athena"

# 3. Import Agent
from agents.athena.agent import run_athena_task

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_athena.py \"Task description\"")
    else:
        run_athena_task(sys.argv[1])