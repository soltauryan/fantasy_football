import sys
import os
import argparse
import subprocess

def run_script(script_path, args=None):
    """Runs a python script as a subprocess."""
    cmd = [sys.executable, script_path]
    if args:
        cmd.extend(args)
    
    print(f"\n[Running]: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[Error] Script failed with exit code {e.returncode}")
        # Stop on ingestion failure
        if "ingest" in script_path:
             sys.exit(e.returncode)

def main():
    parser = argparse.ArgumentParser(description="Multi-Team Analysis (Custom)")
    parser.add_argument("--skip-refresh", action="store_true", help="Skip data ingestion")
    args = parser.parse_args()

    print(f"{'='*60}")
    print("      Multi-Team Analysis (Custom)")
    print(f"{'='*60}")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ingest_script = os.path.join(base_dir, "etl", "ingest_espn.py")
    optimizer_script = os.path.join(base_dir, "analysis", "weekly_optimizer.py")

    # 1. Refresh Data ONCE
    if not args.skip_refresh:
        print("\n--- Step 1: Refreshing Data (ONCE) ---")
        run_script(ingest_script)
    else:
        print("\n--- Step 1: Refreshing Data (SKIPPED) ---")

    # 2. Analyze Multiple Teams
    teams_to_analyze = ["SoltyTears4U", "Serving Punt"]
    
    print("\n--- Step 2: Running Analysis for Teams ---")
    for team in teams_to_analyze:
        print(f"\nProcessing {team}...")
        run_script(optimizer_script, ["--team", team])

    print(f"\n{'='*60}")
    print("Multi-Team Analysis Complete.")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
