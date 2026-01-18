import subprocess
import sys
import time
import os

def run_step(script_path, description):
    print(f"\n{'='*60}")
    print(f"Running Step: {description}")
    print(f"Script: {script_path}")
    print(f"{'='*60}\n")
    
    start_time = time.time()
    try:
        # Run the script using the current python interpreter
        result = subprocess.run(
            [sys.executable, script_path],
            check=True,
            capture_output=False  # Let output flow to stdout
        )
        duration = time.time() - start_time
        print(f"\n[SUCCESS] {description} completed in {duration:.2f} seconds.")
    except subprocess.CalledProcessError as e:
        print(f"\n[FAILURE] {description} failed with exit code {e.returncode}.")
        sys.exit(e.returncode)

def main():
    print("Starting Fantasy Football Data Pipeline...")
    overall_start = time.time()



    # 1. Bronze Layer (Ingestion)
    run_step(os.path.join("etl", "ingest_bronze.py"), "Bronze Layer Ingestion")

    # 2. Silver Layer (Transformation)
    run_step(os.path.join("etl", "transform_silver.py"), "Silver Layer Transformation")

    # 3. Gold Layer (Master Rankings)
    run_step(os.path.join("etl", "generate_master_rankings.py"), "Gold Layer (Master Rankings)")

    # 4. Analytics (EDA)
    run_step(os.path.join("eda", "analyze_nextgen.py"), "Exploratory Data Analysis")

    overall_duration = time.time() - overall_start
    print(f"\n{'='*60}")
    print(f"Pipeline Completed Successfully in {overall_duration:.2f} seconds.")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
