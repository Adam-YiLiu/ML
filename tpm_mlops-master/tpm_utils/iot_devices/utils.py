import subprocess

from constants import TSS_UTILS_DIR


def run_cmd(cmd: str, check=True, tpm_cmd: bool = False):
    """Run a shell command and return the output along with the return code."""
    # if tpm command, change directory to TSS utilities
    if tpm_cmd:
        pwd = subprocess.run("pwd", shell=True, capture_output=True, text=True, check=check)
        pwd = pwd.stdout.rstrip("\n")
        cmd = f"cd {TSS_UTILS_DIR} && {cmd}"

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check)

    # if tpm command, switch back to original working directory
    if tpm_cmd:
        subprocess.run(f"cd {pwd}", shell=True, check=check)

    return result.stdout, result.stderr, result.returncode
