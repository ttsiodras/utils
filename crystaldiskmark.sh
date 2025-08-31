#!/bin/bash

# CrystalDiskMark Clone for Linux using fio
# Mirrors the 4 standard CrystalDiskMark tests

# Default values
TEST_SIZE="1G"
TEST_TIME="60"
TEST_DIR="."
DEVICE=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo "Options:"
    echo "  -d, --device DEVICE    Test raw device (e.g., /dev/sda)"
    echo "  -p, --path PATH        Test directory path (default: current directory)"
    echo "  -s, --size SIZE        Test file size (default: 1G)"
    echo "  -t, --time TIME        Test duration in seconds (default: 60)"
    echo "  -h, --help            Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 -d /dev/sda                    # Test raw device"
    echo "  $0 -p /mnt/storage -s 2G -t 30   # Test filesystem with custom size/time"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--device)
            DEVICE="$2"
            shift 2
            ;;
        -p|--path)
            TEST_DIR="$2"
            shift 2
            ;;
        -s|--size)
            TEST_SIZE="$2"
            shift 2
            ;;
        -t|--time)
            TEST_TIME="$2"
            shift 2
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            print_usage
            exit 1
            ;;
    esac
done

# Check if fio is installed
if ! command -v fio &> /dev/null; then
    echo -e "${RED}Error: fio is not installed${NC}"
    echo "Please install fio: sudo apt install fio  # or equivalent for your distro"
    exit 1
fi

# Set target based on device or directory
if [[ -n "$DEVICE" ]]; then
    if [[ ! -e "$DEVICE" ]]; then
        echo -e "${RED}Error: Device $DEVICE does not exist${NC}"
        exit 1
    fi
    TARGET="--filename=$DEVICE"
    TARGET_NAME="$DEVICE"
    echo -e "${YELLOW}Warning: Testing raw device $DEVICE - this will overwrite data!${NC}"
    read -p "Are you sure you want to continue? (yes/no): " confirm
    if [[ $confirm != "yes" ]]; then
        echo "Aborted."
        exit 0
    fi
else
    if [[ ! -d "$TEST_DIR" ]]; then
        echo -e "${RED}Error: Directory $TEST_DIR does not exist${NC}"
        exit 1
    fi
    TARGET="--directory=$TEST_DIR"
    TARGET_NAME="$TEST_DIR"
fi

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                    CrystalDiskMark Clone for Linux                   ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}Target:${NC} $TARGET_NAME"
echo -e "${GREEN}Test Size:${NC} $TEST_SIZE"
echo -e "${GREEN}Test Duration:${NC} ${TEST_TIME}s per test"
echo ""

run_test() {
    local test_name="$1"
    local rw_type="$2"
    local block_size="$3"
    local description="$4"
    local queue_depth="${5:-32}"  # Default to 32 if not specified
    
    echo -e "${YELLOW}Running $description...${NC}"
    
    # Create temporary file for fio output
    local temp_file=$(mktemp)
    
    # Build fio command with appropriate parameters
    local fio_cmd="fio --name=$test_name --rw=$rw_type --bs=$block_size --iodepth=$queue_depth --numjobs=1 --size=$TEST_SIZE --runtime=$TEST_TIME --group_reporting --ioengine=libaio --direct=1 $TARGET"
    
    # Add random-specific parameters only for random tests
    if [[ "$rw_type" =~ ^rand ]]; then
        fio_cmd="$fio_cmd --randrepeat=1 --norandommap"
    fi
    
    # Run fio with proper output and wait for completion
    eval $fio_cmd > "$temp_file" 2>&1
    
    # Read the complete output
    local fio_output=$(cat "$temp_file")
    rm -f "$temp_file"
    
    # Look for the actual results in different formats
    local result_line=""
    
    # Try different grep patterns for results
    if [[ "$rw_type" =~ ^(read|randread)$ ]]; then
        result_line=$(echo "$fio_output" | grep -E "(READ:|read:)" | tail -1)
    else
        result_line=$(echo "$fio_output" | grep -E "(WRITE:|write:)" | tail -1)
    fi
    
    # Alternative: look for bandwidth/IOPS in any line
    if [[ -z "$result_line" ]]; then
        result_line=$(echo "$fio_output" | grep -E "(BW=|bw=|IOPS=|iops=)" | tail -1)
    fi
    
    if [[ -n "$result_line" ]]; then
        # Extract bandwidth and IOPS with flexible patterns
        local bandwidth=$(echo "$result_line" | grep -oE "(BW=|bw=)[^,)[:space:]]*" | cut -d'=' -f2)
        local iops=$(echo "$result_line" | grep -oE "(IOPS=|iops=)[^,)[:space:]]*" | cut -d'=' -f2)
        
        if [[ -n "$bandwidth" && -n "$iops" ]]; then
            echo -e "  ${GREEN}Bandwidth:${NC} $bandwidth, ${GREEN}IOPS:${NC} $iops"
        elif [[ -n "$bandwidth" ]]; then
            echo -e "  ${GREEN}Bandwidth:${NC} $bandwidth"
        elif [[ -n "$iops" ]]; then
            echo -e "  ${GREEN}IOPS:${NC} $iops"
        else
            # Show the result line as-is
            echo -e "  ${GREEN}Result:${NC} $(echo "$result_line" | sed 's/^[[:space:]]*//' | cut -c1-100)"
        fi
    else
        echo -e "  ${RED}No results found${NC}"
        # Show relevant lines for debugging
        echo "Debug output:"
        echo "$fio_output" | grep -E "(error|Error|failed|Failed|READ|WRITE|BW=|IOPS=)" | head -3
    fi
    echo ""
}

# Run the 4 standard CrystalDiskMark test patterns (each as read + write)
echo -e "${BLUE}═══════════════════════════════════════════════════════════════════════${NC}"

# SEQ1M Q8T1 - Sequential 1MB, Queue Depth 8, 1 Thread
run_test "seq1m-q8t1-read" "read" "1M" "SEQ1M Q8T1 Read" "8"
run_test "seq1m-q8t1-write" "write" "1M" "SEQ1M Q8T1 Write" "8"

# SEQ1M Q1T1 - Sequential 1MB, Queue Depth 1, 1 Thread  
run_test "seq1m-q1t1-read" "read" "1M" "SEQ1M Q1T1 Read" "1"
run_test "seq1m-q1t1-write" "write" "1M" "SEQ1M Q1T1 Write" "1"

# RND4K Q32T1 - Random 4K, Queue Depth 32, 1 Thread
run_test "rnd4k-q32t1-read" "randread" "4k" "RND4K Q32T1 Read" "32"
run_test "rnd4k-q32t1-write" "randwrite" "4k" "RND4K Q32T1 Write" "32"

# RND4K Q1T1 - Random 4K, Queue Depth 1, 1 Thread
run_test "rnd4k-q1t1-read" "randread" "4k" "RND4K Q1T1 Read" "1"
run_test "rnd4k-q1t1-write" "randwrite" "4k" "RND4K Q1T1 Write" "1"

echo -e "${BLUE}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}All tests completed!${NC}"

# Clean up test files if testing filesystem
if [[ -z "$DEVICE" ]]; then
    rm -f "$TEST_DIR"/{seq1m-q8t1-read,seq1m-q8t1-write,seq1m-q1t1-read,seq1m-q1t1-write,rnd4k-q32t1-read,rnd4k-q32t1-write,rnd4k-q1t1-read,rnd4k-q1t1-write}.0.0
fi
