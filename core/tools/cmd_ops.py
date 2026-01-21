import subprocess
import os

def run_command(command: str, cwd: str = os.getcwd()) -> str:
    """รันคำสั่ง Shell"""
    try:
        # Security Check (Basic)
        forbidden = ["rm -rf /", "format c:"]
        if any(f in command.lower() for f in forbidden):
            return "❌ Error: Command not allowed."

        result = subprocess.run(
            command, shell=True, cwd=cwd, capture_output=True, text=True
        )
        output = result.stdout + "\n" + result.stderr
        return output.strip()
    except Exception as e:
        return f"❌ Execution Error: {e}"