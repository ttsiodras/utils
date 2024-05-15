# GDB helper (command x16) to dump 16 columns of data instead of 8
# From inside gdb, just "source /path/to/x16.py" and then use it via
#
#  x16 252 ptrVar  # dumps 252 bytes from wherever ptrVal points to

class X16Command(gdb.Command):
    """Examine memory in 16 column format."""
    
    def __init__(self):
        super(X16Command, self).__init__("x16", gdb.COMMAND_DATA)
    
    def invoke(self, arg, from_tty):
        args = gdb.string_to_argv(arg)
        if len(args) != 2:
            print("Usage: x16 <count> <address>")
            return
        
        count = int(args[0])
        address = gdb.parse_and_eval(args[1])
        
        values = gdb.execute(f"x/{count}xb {address}", to_string=True)
        
        print("x16 output:")
        # Process and reformat the output
        good_addr = ''
        previous_bytes_values = []
        for line in values.splitlines():
            data = line.split()
            addr, bytes_values = data[0], data[1:]
            if len(previous_bytes_values) == 8:
                previous_bytes_values.extend(['     '])
                previous_bytes_values.extend(bytes_values)
                print(good_addr, ' '.join(previous_bytes_values))
                previous_bytes_values = []
            else:
                previous_bytes_values.extend(bytes_values)
                good_addr = addr
        if previous_bytes_values:
            print(good_addr, ' '.join(previous_bytes_values))
            
# Register the command
X16Command()
