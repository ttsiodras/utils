#!/bin/bash
#
# Usage:
#     execOnChange-inotify.sh "some command with params" "-iname *.md"
#
# Uses inotify to efficiently monitor file changes matching the filespec
# and execute the command when changes occur. Handles concurrent builds properly.
#
if [ $# -ne 2 ] ; then 
    echo 'Usage: execOnChange-inotify.sh "some command with params" "-iname ..."'
    exit 1
fi

command="$1"
shift
fileSpec="$@"

# Check if inotify-tools is available
if ! command -v inotifywait &> /dev/null; then
    echo "Error: inotifywait not found. Please install inotify-tools:"
    echo "  Ubuntu/Debian: sudo apt-get install inotify-tools"
    echo "  CentOS/RHEL: sudo yum install inotify-tools"
    echo "  Arch: sudo pacman -S inotify-tools"
    exit 1
fi

# Function to check if a file matches the filespec
matches_filespec() {
    local file="$1"
    # Use find to test if the file matches the filespec
    result=$(find "$file" -maxdepth 0 -type f \( $fileSpec \) 2>/dev/null)
    [ -n "$result" ]
}

# Global state
build_running=false
build_requested=false
build_pid=""

# Function to execute command
execute_command() {
    if $build_running; then
        echo "Build already running (PID $build_pid), will restart after completion..."
        build_requested=true
        return
    fi
    
    echo -e "\nExecuting $command ..."
    
    # Start build in background and track its PID
    bash -c "$command" &
    build_pid=$!
    build_running=true
    build_requested=false
    
    # Monitor the build completion in background
    (
        wait $build_pid
        build_exit_code=$?
        
        echo "Build completed (exit code: $build_exit_code)"
        
        # Signal the main loop that build is done
        echo "BUILD_DONE:$build_exit_code" > /tmp/build_status.$$
    ) &
}

# Cleanup function
cleanup() {
    echo -e "\nShutting down..."
    if [[ -n "$build_pid" ]] && kill -0 "$build_pid" 2>/dev/null; then
        echo "Terminating running build (PID $build_pid)..."
        kill "$build_pid" 2>/dev/null
        wait "$build_pid" 2>/dev/null
    fi
    rm -f /tmp/build_status.$$
    exit 0
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

# Simple time-based debouncing
last_trigger=0
debounce_seconds=0.3

should_trigger() {
    local current=$(date +%s)
    local elapsed=$((current - last_trigger))
    
    if [ $elapsed -ge 1 ] || [ $last_trigger -eq 0 ]; then
        last_trigger=$current
        return 0
    else
        last_trigger=$current  # Update time but don't trigger yet
        return 1
    fi
}

echo "Monitoring for changes matching: $fileSpec"
echo "Press Ctrl+C to stop..."

# Monitor both file changes and build completion
{
    # File change monitoring
    inotifywait -m -r -e close_write,moved_to --format 'FILE:%w%f:%e' . 2>/dev/null &
    inotify_pid=$!
    
    # Build status monitoring  
    while true; do
        if [ -f "/tmp/build_status.$$" ]; then
            status=$(cat /tmp/build_status.$$ 2>/dev/null)
            if [[ "$status" =~ BUILD_DONE:([0-9]+) ]]; then
                rm -f /tmp/build_status.$$
                echo "BUILD_STATUS:${BASH_REMATCH[1]}"
            fi
        fi
        sleep 0.1
    done &
    status_pid=$!
    
    # Wait for either
    wait
} | while IFS=':' read prefix file_or_code event_or_empty; do
    case "$prefix" in
        "FILE")
            file="$file_or_code"
            event="$event_or_empty"
            
            # Skip if file doesn't exist
            if [ ! -f "$file" ]; then
                continue
            fi
            
            # Check if the file matches our filespec
            if matches_filespec "$file"; then
                echo "File changed: $file ($event)"
                
                # Simple debouncing: only trigger if enough time has passed
                if should_trigger; then
                    execute_command
                fi
            fi
            ;;
        "BUILD_STATUS")
            exit_code="$file_or_code"
            build_running=false
            build_pid=""
            
            # If another build was requested while this one was running, start it
            if $build_requested; then
                echo "Starting queued build..."
                execute_command
            fi
            ;;
    esac
done

# Cleanup background processes
kill $inotify_pid $status_pid 2>/dev/null
