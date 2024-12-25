import psutil
import subprocess
import time

# Define thresholds for CPU load, IRQ count, and IPC
LOAD_THRESHOLD = 10  # Example threshold for CPU load (%)
IRQ_THRESHOLD = 100000  # Example threshold for IRQ count
IPC_THRESHOLD = 0.9  # Example threshold for IPC value
MIN_ACTIVE_CORES = 1  # Minimum active cores to maintain

# Global variables to manage active and offline cores
active_cores = set()
offline_cores = set()

# Track IRQ count over time
last_irq_count = 0

def get_cpu_load():
    """Get the average CPU load."""
    return psutil.cpu_percent(interval=1)

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
    """Retrieve IPC (Instructions Per Cycle) using `perf`."""
    try:
        output = subprocess.check_output("perf stat -e instructions,cycles sleep 1 2>&1", shell=True).decode()
        # Parse the instructions and cycles from the output
        instructions = int([line for line in output.splitlines() if "instructions" in line][0].split()[0].replace(",", ""))
        cycles = int([line for line in output.splitlines() if "cycles" in line][0].split()[0].replace(",", ""))
        
        ipc = instructions / cycles
        return ipc
    except Exception as e:
        print(f"[ERROR] Error fetching IPC: {e}")
        return 0

def get_cpu_frequency(core_id):
    """Get CPU frequency for a given core."""
    try:
        freq = subprocess.check_output(f"cat /sys/devices/system/cpu/cpu{core_id}/cpufreq/scaling_cur_freq", shell=True)
        return int(freq.decode().strip())
    except subprocess.CalledProcessError:
        return 0  # Handle error if frequency can't be retrieved

def set_cpu_online_state(core_id, state):
    """Set a core to online or offline."""
    try:
        with open(f"/sys/devices/system/cpu/cpu{core_id}/online", "w") as f:
            f.write("1" if state == "online" else "0")
        print(f"[INFO] Set core {core_id} to {state}.")
    except IOError as e:
        print(f"[ERROR] Failed to set core {core_id} to {state}: {e}")

def set_governor(governor):
    """Set the CPU governor for all cores."""
    for core_id in range(psutil.cpu_count()):
        try:
            with open(f"/sys/devices/system/cpu/cpu{core_id}/cpufreq/scaling_governor", "w") as f:
                f.write(governor)
            print(f"[INFO] Set governor for core {core_id} to {governor}.")
        except IOError as e:
            print(f"[ERROR] Failed to set governor for core {core_id}: {e}")

def display_metrics(cpu_load, irq_count, ipc):
    """Display metrics in a table format."""
    print("\nMetrics                           Value")
    print("-----------------------------------------")
    print(f"Average CPU Load (%)               {cpu_load}")
    print(f"Total IRQ Count                    {irq_count}")
    print(f"CPU Governor                       powersave")
    print(f"Active Cores                       {len(active_cores)}")

def get_active_cores():
    """Dynamically get active cores from the system."""
    active_cores = []
    for core_id in range(psutil.cpu_count()):
        try:
            with open(f"/sys/devices/system/cpu/cpu{core_id}/online", "r") as f:
                if f.read().strip() == "1":
                    active_cores.append(core_id)
        except FileNotFoundError:
            continue
    return active_cores

def display_core_usage_and_state():
    """Display current core usage and state."""
    global active_cores  # Use global active_cores to ensure it's updated correctly
    active_cores = get_active_cores()  # Get real-time active cores
    print("\nCore Usage and State:")
    print("+-----------+-------------+---------+------------------+")
    print("|   Core ID |   Usage (%) | State   | CPU Freq (MHz)   |")
    print("+===========+=============+=========+==================+")
    for core_id in active_cores:
        core_usage = psutil.cpu_percent(percpu=True)[core_id]
        current_freq = get_cpu_frequency(core_id) / 1000 if get_cpu_frequency(core_id) != 0 else 0  # Convert kHz to MHz
        state = "online"
        print(f"| {core_id:<9} | {core_usage:<11} | {state:<7} | {current_freq:<16} |")
        print("+-----------+-------------+---------+------------------+")

def manage_core_activity(cpu_load, irq_count, ipc):
    """Manage core activity based on CPU load, IRQ count, and IPC."""
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
            active_cores.append(core_to_activate)
            set_cpu_online_state(core_to_activate, 'online')  # Set core online
            set_governor("performance")
            print(f"[INFO] Activated core {core_to_activate} due to high load.")

    # Reassign processes to active cores
    process_ids_to_reassign = []  # Collect processes that need reassignment
    for process_id in psutil.process_iter(['pid', 'cpu_num']):
        try:
            process = process_id.info
            # Check if process is on an offline core and assign to an active core
            if process['cpu_num'] not in active_cores:
                process_ids_to_reassign.append(process['pid'])
                # Find a valid active core (one that is online)
                valid_active_cores = [core for core in active_cores if subprocess.check_output(f"cat /sys/devices/system/cpu/cpu{core}/online", shell=True).decode().strip() == "1"]
                
                if valid_active_cores:
                    # Assign to the first valid core
                    new_core = valid_active_cores[0]
                    try:
                        psutil.Process(process['pid']).cpu_affinity([new_core])
                        print(f"[INFO] Reassigned process {process['pid']} from core {process['cpu_num']} to core {new_core}.")
                    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                        pass  # Skip processes that are not available or cannot be reassigned
                else:
                    print(f"[WARN] No valid active cores available for reassignment.")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue  # Skip processes that no longer exist or are inaccessible

    if process_ids_to_reassign:
        # Print processes reassigned to active cores
        print(f"[INFO] Reassigned the following processes to active cores:")
        print(", ".join(map(str, process_ids_to_reassign)))

    # Print active cores separately
    print(f"[INFO] Active cores: {', '.join(map(str, active_cores))}")

def main():
    global active_cores, offline_cores
    active_cores = get_active_cores()  # Get the active cores dynamically from the system
    offline_cores = set()

    while True:
        # Get metrics
        cpu_load = get_cpu_load()
        irq_count = get_irq_count()
        ipc = get_ipc()

        # Display the metrics
        display_metrics(cpu_load, irq_count, ipc)

        # Manage core activity based on metrics
        manage_core_activity(cpu_load, irq_count, ipc)

        # Display the current core usage and state
        display_core_usage_and_state()

        # Wait before checking again
        time.sleep(5)

if __name__ == "__main__":
    main()

