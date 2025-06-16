import yappi
import sys

# Get the profile file path from command line arguments, default to 'kubezen.prof'
profile_file = sys.argv[1] if len(sys.argv) > 1 else 'kubezen.prof'

print(f"Analyzing profiler data from '{profile_file}'...\n")

try:
    # Load the stats from the ystat file
    stats = yappi.YFuncStats(profile_file)

    # Manually sort the statistics by total time ('ttot') in descending order
    # This avoids issues with library constants.
    sorted_stats = sorted(stats, key=lambda s: s.ttot, reverse=True)
    
    # Define the header
    header = f"{'Function':<80} {'Calls':<8} {'SubTime':<12} {'TotalTime':<12}"
    print(header)
    print('-' * len(header))

    # Print the top 30 functions from the manually sorted list
    for stat in sorted_stats[:30]:
        print(f"{stat.name:<80} {stat.ncall:<8} {stat.tsub:<12.6f} {stat.ttot:<12.6f}")

except Exception as e:
    print(f"Failed to read or analyze the profile file: {e}")
    print("Please ensure the file exists and was generated correctly.") 