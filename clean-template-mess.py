#!/usr/bin/env python3
"""
Pretty-print C++ template instantiations with indentation.
Usage: c++filt | python3 format_templates.py
   or: python3 format_templates.py < input.txt
"""

import sys
import re

def count_commas_in_template(text, start_pos):
    """Count commas in a template starting from '<' position."""
    depth = 0
    comma_count = 0
    i = start_pos
    
    while i < len(text):
        if text[i] == '<':
            depth += 1
        elif text[i] == '>':
            depth -= 1
            if depth == 0:
                return comma_count
        elif text[i] == ',' and depth == 1:
            comma_count += 1
        i += 1
    
    return comma_count

def format_cpp_type(text):
    """Format C++ type with indentation like jq does for JSON.
    Single-argument templates stay on one line."""
    result = []
    indent = 0
    i = 0
    
    while i < len(text):
        char = text[i]
        
        if char == '<':
            # Check if this is a single-argument template
            comma_count = count_commas_in_template(text, i)
            
            if comma_count == 0:
                # Single argument - keep on same line
                # Find the matching '>'
                depth = 0
                j = i
                while j < len(text):
                    if text[j] == '<':
                        depth += 1
                    elif text[j] == '>':
                        depth -= 1
                        if depth == 0:
                            # Copy everything from '<' to '>' inclusive
                            result.append(text[i:j+1])
                            i = j
                            break
                    j += 1
            else:
                # Multiple arguments - format with newlines
                result.append(char)
                result.append('\n')
                indent += 2
                result.append(' ' * indent)
        elif char == '>':
            result.append('\n')
            indent -= 2
            result.append(' ' * indent)
            result.append(char)
        elif char == ',':
            result.append(char)
            # Look ahead to see if there's a space
            if i + 1 < len(text) and text[i + 1] == ' ':
                i += 1  # Skip the space
            result.append('\n')
            result.append(' ' * indent)
        else:
            result.append(char)
        
        i += 1
    
    return ''.join(result)

def main():
    for line in sys.stdin:
        # Strip trailing whitespace
        line = line.rstrip()
        
        # Process the line
        formatted = format_cpp_type(line)
        print(formatted)
        print()  # Extra newline between entries

if __name__ == '__main__':
    main()
