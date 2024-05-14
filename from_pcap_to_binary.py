#!.scapy/bin/python3
import argparse

from scapy.all import *

def extract_eth_payloads(tcpdump_file, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    packets = rdpcap(tcpdump_file)

    for i, packet in enumerate(packets):
        if Ether in packet:
            eth_header = bytes(packet[Ether])
            filename = os.path.join(output_dir, f'frame_{i:05d}.bin')
            with open(filename, 'wb') as f:
                f.write(eth_header)


def main():
    parser = argparse.ArgumentParser(
                    prog='tcpdump2binary',
                    description='Convert tcpdump capture to separate binary ETH frames',
                    epilog='Uses scapy for the actual extraction.')
    parser.add_argument('filename', help='filename containing tcpdump capture')
    parser.add_argument('-o', '--outputFolder', help='The folder to store the output ETH frames', default='extractedFrames')
    args = parser.parse_args()

    tcpdump_file = args.filename
    output_dir = args.outputFolder
    extract_eth_payloads(tcpdump_file, output_dir)

if __name__ == "__main__":
    main()
