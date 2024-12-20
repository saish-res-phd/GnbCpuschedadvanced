import psutil
import subprocess
import time
import os

# Constants
LOAD_THRESHOLD = 10      # CPU load (%) to activate/deactivate cores
IRQ_THRESHOLD = 100000   # IRQ threshold to activate cores
IPC_THRESHOLD = 0.7      # IPC threshold to activate cores
MIN_ACTIVE_CORES = 1     # Minimum cores to keep active
MAX_CORES = psutil.cpu_count(logical=True)

# Functions
def get_irq_count():
    """Retrieve IRQ count from the system for the specific interface."""
    try:
        irq_output = subprocess.check_output("cat /proc/interrupts", shell=True).decode().splitlines()
        irq_count = sum(int(line.split()[1]) for line in irq_output if 'eno1' in line)
        return irq_count
    except Exception as e:
        print(f"[ERROR] Error fetching IRQ count: {e}")
        return 0

def get_ipc():
    """Retrieve IPC (Instructions Per Cycle) from psutil."""
    try:
        ipc = 0.75  # Example IPC value (you may replace this with an actual metric)
        return ipc
    except Exception as e:
        print(f"[ERROR] Error fetching IPC: {e}")
        return 0

def set_cpu_online_state(core_id, state):
    """Set a CPU core online/offline, skip core 0 if there's an error."""
    try:
        if core_id == 0:
            print("[INFO] Skipping core 0 due to access issues.")
            return

        state_str = '1' if state == 'online' else '0'
        with open(f"/sys/devices/system/cpu/cpu{core_id}/online", "w") as f:
            f.write(state_str)
        print(f"[INFO] Set core {core_id} to {state}.")
    except Exception as e:
        print(f"[ERROR] Error setting CPU {core_id} state to {state}: {e}")

def set_governor(governor):
    """Set CPU governor."""
    try:
        subprocess.call(f"sudo cpupower frequency-set -g {governor}", shell=True)
        print(f"[INFO] Governor set to {governor}.")
    except Exception as e:
        print(f"[ERROR] Error setting governor to {governor}: {e}")

def activate_all_cores():
    """Activate all CPU cores initially, except core 0."""
    for core_id in range(1, MAX_CORES):
        try:
            set_cpu_online_state(core_id, 'online')  # Set core online
        except Exception as e:
            print(f"[ERROR] Error activating core {core_id}: {e}")
    
    print("[INFO] All CPU cores (except core 0) are now activated.")

def get_core_usage_and_state():
    """Get the usage and state of each CPU core, skipping core 0."""
    core_usage = {}
    for core_id in range(MAX_CORES):
        if core_id == 0:
            continue  # Skip core 0 due to access issues
        
        try:
            usage = psutil.cpu_percent(interval=1, percpu=True)[core_id]
            state = "online" if subprocess.check_output(f"cat /sys/devices/system/cpu/cpu{core_id}/online", shell=True).decode().strip() == "1" else "offline"
            core_usage[core_id] = {"usage": usage, "state": state}
        except Exception as e:
            print(f"[ERROR] Error fetching state of core {core_id}: {e}")
            core_usage[core_id] = {"usage": 0, "state": "unknown"}
    
    return core_usage

# Core management functions
def manage_core_activity(cpu_load, irq_count, ipc):
    global active_cores, offline_cores

    print(f"[DEBUG] manage_core_activity: cpu_load={cpu_load}, irq_count={irq_count}, ipc={ipc}")

    # Deactivate cores if conditions are met
    if (cpu_load < LOAD_THRESHOLD and irq_count < IRQ_THRESHOLD and ipc < IPC_THRESHOLD and len(active_cores) > MIN_ACTIVE_CORES):
        print(f"[DEBUG] Conditions met for core deactivation.")
        # Deactivate the last core in active_cores
        core_to_deactivate = active_cores.pop()
        offline_cores.add(core_to_deactivate)
        set_cpu_online_state(core_to_deactivate, 'offline')  # Set core offline
        set_governor("powersave")
        print(f"[INFO] Deactivated core {core_to_deactivate} due to low load.")

    # Activate cores if conditions are met
    elif (cpu_load >= LOAD_THRESHOLD or irq_count >= IRQ_THRESHOLD or ipc >= IPC_THRESHOLD):
        if offline_cores:
            # Activate the first core in offline_cores
            core_to_activate = offline_cores.pop()
            active_cores.add(core_to_activate)
            set_cpu_online_state(core_to_activate, 'online')  # Set core online
            set_governor("performance")
            print(f"[INFO] Activated core {core_to_activate} due to high load.")

def set_core_state(core_id, cpu_load, irq_count, ipc):
    """Set each core's state based on the metrics."""
    print(f"[DEBUG] Evaluating core {core_id} state: cpu_load={cpu_load}, irq_count={irq_count}, ipc={ipc}")
    if cpu_load < LOAD_THRESHOLD and irq_count < IRQ_THRESHOLD and ipc < IPC_THRESHOLD:
        # Set core to offline if all conditions are below the thresholds
        print(f"[DEBUG] Setting core {core_id} to offline.")
        set_cpu_online_state(core_id, 'offline')
    elif cpu_load >= LOAD_THRESHOLD or irq_count >= IRQ_THRESHOLD or ipc >= IPC_THRESHOLD:
        # Set core to online if any condition exceeds the threshold
        print(f"[DEBUG] Setting core {core_id} to online.")
        set_cpu_online_state(core_id, 'online')
    else:
        # Default idle state
        print(f"[DEBUG] Setting core {core_id} to offline (default).")
        set_cpu_online_state(core_id, 'offline')

def print_core_status():
    global active_cores, offline_cores

    # Display current core status
    print("\nCore Status:")
    print("Active Cores:", ", ".join(map(str, active_cores)))
    print("Offline Cores:", ", ".join(map(str, offline_cores)))

# Main logic
def main():
    # Initialize sets for active and offline cores
    global active_cores, offline_cores
    active_cores = set(range(1, MAX_CORES))  # Initially, assume all cores are active except core 0
    offline_cores = set()

    # Activate all cores initially, except core 0
    activate_all_cores()

    print("[INFO] Dynamic CPU Optimization Script Started")
    while True:
        # Fetch current metrics
        cpu_load = psutil.cpu_percent(interval=1)
        irq_count = get_irq_count()
        ipc = get_ipc()

        # Get core usage and state
        core_usage_and_state = get_core_usage_and_state()

        # Display metrics and core states in tabular format
        print("\nMetrics                           Value")
        print("-----------------------------------------")
        print(f"Average CPU Load (%)               {cpu_load}")
        print(f"Total IRQ Count                    {irq_count}")
        print(f"CPU Governor                       {'powersave' if cpu_load < LOAD_THRESHOLD else 'performance'}")
        print(f"Active Cores                       {len(active_cores)}")

        print("\nCore Usage and State:")
        print("Core ID  |  Usage (%)  |  State")
        print("--------------------------------")
        for core_id, data in core_usage_and_state.items():
            print(f"  {core_id:2}    |    {data['usage']:6.2f}    |  {data['state']}")

        print("\nStatus:")
        print(f"Active Cores: {', '.join(map(str, active_cores))}")
        print(f"Offline Cores: {', '.join(map(str, offline_cores))}")
        
        # Manage core activity based on the metrics
        manage_core_activity(cpu_load, irq_count, ipc)
        
        # Print core status
        print_core_status()

        # Sleep for a short interval before checking again
        time.sleep(5)

if __name__ == "__main__":
    main()
