import subprocess
import sys
import os
import argparse

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
        # We might want to continue or exit depending on severity. 
        # For data ingestion, we should probably stop if it fails.
        if "ingest" in script_path:
             sys.exit(e.returncode)

def main():
    parser = argparse.ArgumentParser(description="Weekly Fantasy Football Tuesday Routine")
    parser.add_argument("--team", type=str, help="Your Team Name (for analysis)")
    parser.add_argument("--skip-refresh", action="store_true", help="Skip data ingestion")
    args = parser.parse_args()

    # Define paths
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ingest_script = os.path.join(base_dir, "etl", "ingest_espn.py")
    optimizer_script = os.path.join(base_dir, "analysis", "weekly_optimizer.py")

    print(f"{'='*60}")
    print("      Fantasy Football Weekly Routine (Tuesday)")
    print(f"{'='*60}")

    # 1. Data Refresh
    if not args.skip_refresh:
        print("\n--- Step 1: Refreshing Data ---")
        run_script(ingest_script)
    else:
        print("\n--- Step 1: Refreshing Data (SKIPPED) ---")

    # 2. Analysis
    print("\n--- Step 2: Running Analysis ---")
    analysis_args = []
    if args.team:
        analysis_args = ["--team", args.team]
    
    run_script(optimizer_script, analysis_args)

    print(f"\n{'='*60}")
    print("Routine Complete.")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
