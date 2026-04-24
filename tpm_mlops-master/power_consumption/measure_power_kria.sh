#!/bin/bash

get_som_power() {
  sudo xmutil xlnx_platformstats | awk -F ':' '/SOM total power/ {gsub(/ /, "", $2); print $2 + 0}'
}

if [ $# -eq 0 ]; then
  echo "Usage: $0 <command>"
  exit 1
fi

echo "[*] Taking initial power reading..."
initial_power=$(get_som_power)
initial_time=$(date +%s)
echo "[${initial_time}] Initial Power: ${initial_power} mW"

echo "[*] Starting workload and power monitoring..."
sample_interval=1  # seconds
samples=()
timestamps=()

# run command in background
"$@" &
cmd_pid=$!

# sample power every second while command is running
while kill -0 "$cmd_pid" 2>/dev/null; do
  power=$(get_som_power)
  timestamp=$(date +%s)
  echo "[${timestamp}] Power: ${power} mW"
  samples+=($power)
  timestamps+=($timestamp)
  sleep $sample_interval
done

# final reading after process exits (not part of average)
final_power=$(get_som_power)
final_time=$(date +%s)
echo "[${final_time}] Final Power (excluded from average): ${final_power} mW"

# calculate average power from samples
total_power=0
for p in "${samples[@]}"; do
  total_power=$((total_power + p))
done
avg_power=$((total_power / ${#samples[@]}))

# duration = number of samples × interval
duration=$(( ${#samples[@]} * sample_interval ))

echo
echo "==== Power Profile Summary ===="
echo "Initial power reading    : ${initial_power} mW"
echo "Samples taken            : ${#samples[@]}"
echo "Monitoring time          : ${duration} seconds"
echo "Average power            : ${avg_power} mW"
echo "Final power only reading : ${final_power} mW"
echo "==============================="
