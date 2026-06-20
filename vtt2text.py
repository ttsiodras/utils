r"""
Convert YouTube subtitles(vtt) to human readable text.

Download only subtitles from YouTube with youtube-dl:
youtube-dl  --skip-download --convert-subs vtt <video_url>

To convert all vtt files inside a directory:
find . -name "*.vtt" -exec python vtt2text_new.py {} \;
"""

import sys
import re
import argparse
import html

def remove_tags(text):
    """
    Remove vtt markup tags
    """
    # Remove timestamps inside text tags <00:00:00.000>
    text = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', text)
    # Remove <c> and </c> tags, and any attributes inside <c ...>
    text = re.sub(r'</?c(\.color\w+)?>', '', text)
    return html.unescape(text)

def parse_vtt(content):
    """
    Parse VTT content into a list of (timestamp, text) tuples.
    """
    # Remove header
    header_end = content.find('\n\n')
    if header_end == -1:
        # If no double newline, look for the first timestamp
        header_end = content.find('00:00:00.000')
        if header_end == -1:
            # Just start from the beginning
            header_end = 0
    
    body = content[header_end:]
    
    # Split by timestamps
    # A timestamp looks like 00:00:00.000 --> 00:00:00.000 ...
    pattern = r'(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3}).*?\n'
    
    # We use re.split but keep the timestamps
    parts = re.split(pattern, body)
    
    captions = []
    # re.split with capturing groups returns:
    # [prefix, start_time, end_time, text, start_time, end_time, text, ...]
    for i in range(1, len(parts), 3):
        start_time = parts[i]
        # end_time = parts[i+1]
        text = parts[i+2].strip() if i+2 < len(parts) else ""
        text = remove_tags(text)
        captions.append((start_time, text))
        
    return captions

def merge_overlapping(captions):
    """
    Merge cumulative captions by removing overlapping prefixes.
    """
    full_text = ""
    for _, cap_text in captions:
        cap_text = cap_text.strip()
        if not cap_text:
            continue
        
        # Find the longest overlap between the end of full_text and the start of cap_text
        max_overlap = 0
        for i in range(1, min(len(full_text), len(cap_text)) + 1):
            if full_text.endswith(cap_text[:i]):
                max_overlap = i
        
        full_text += cap_text[max_overlap:]
        
    return full_text

def wrap_text(text, width=80):
    """
    Wrap text to a given width.
    """
    words = text.split()
    lines = []
    current_line = []
    current_length = 0
    
    for word in words:
        if current_length + len(word) + 1 <= width:
            current_line.append(word)
            current_length += len(word) + 1
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_length = len(word)
            
    if current_line:
        lines.append(" ".join(current_line))
        
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Convert VTT to human readable text")
    parser.add_argument("vtt_file", help="Input VTT file")
    parser.add_argument("--keep-timestamps", action="store_true", help="Keep timestamps in output")
    args = parser.parse_args()

    vtt_file_name = args.vtt_file
    txt_name = re.sub(r'\.vtt$', '.txt', vtt_file_name)
    
    with open(vtt_file_name, 'r', encoding='utf-8') as f:
        content = f.read()
    
    captions = parse_vtt(content)
    
    if args.keep_timestamps:
        final_lines = []
        last_text = ""
        for ts, text in captions:
            if not text.strip():
                continue
            if text == last_text:
                continue
            
            short_ts = ts[:5]
            if not final_lines or final_lines[-1][0] != short_ts:
                final_lines.append((short_ts, ""))
            
            final_lines.append(("", text))
            last_text = text
            
        with open(txt_name, 'w', encoding='utf-8') as f:
            for ts, text in final_lines:
                if ts:
                    f.write(f"\n{ts}\n")
                else:
                    f.write(text + "\n")
    else:
        merged_text = merge_overlapping(captions)
        parts = merged_text.split('>>')
        final_output = []
        for part in parts:
            if not part.strip():
                continue
            wrapped = wrap_text(part.strip(), width=80)
            final_output.append(">> " + wrapped if part != parts[0] or merged_text.startswith('>>') else wrapped)
            
        with open(txt_name, 'w', encoding='utf-8') as f:
            f.write("\n\n".join(final_output))

if __name__ == "__main__":
    main()
