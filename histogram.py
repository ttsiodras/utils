#!/usr/bin/env python3
import sys
import argparse
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import colors
from matplotlib.ticker import PercentFormatter

fontsize = 15


def is_outlier(points, thresh=3.5):
    """
    Shamelessly copied from:
    https://stackoverflow.com/questions/11882393/matplotlib-disregard-outliers-when-plotting

    Returns a boolean array with True if points are outliers and False 
    otherwise.

    Parameters:
    -----------
        points : An numobservations by numdimensions array of observations
        thresh : The modified z-score to use as a threshold. Observations with
            a modified z-score (based on the median absolute deviation) greater
            than this value will be classified as outliers.

    Returns:
    --------
        mask : A numobservations-length boolean array.

    References:
    ----------
        Boris Iglewicz and David Hoaglin (1993), "Volume 16: How to Detect and
        Handle Outliers", The ASQC Basic References in Quality Control:
        Statistical Techniques, Edward F. Mykytka, Ph.D., Editor. 
    """
    if len(points.shape) == 1:
        points = points[:,None]
    median = np.median(points, axis=0)
    diff = np.sum((points - median)**2, axis=-1)
    diff = np.sqrt(diff)
    med_abs_deviation = np.median(diff)

    modified_z_score = 0.6745 * diff / med_abs_deviation

    return modified_z_score > thresh

def main():
    parser = argparse.ArgumentParser(
                    prog='Histogram via Matplotlib',
                    description='Plot a histogram of data provided over file or stdin',
                    epilog='Uses matplotlib for the actual plot.')
    parser.add_argument('filename', help='filename or \'-\' for stdin; containing one data point per line')
    parser.add_argument('-b', '--buckets', help='The buckets to use for the histogram', default='10')
    parser.add_argument('-r', '--outliersOff', action='store_true', help='disable outliers')
    parser.add_argument('-l', '--label', help='Label to emit in the generated plot', default='Histogram')
    parser.add_argument('-w', '--width', help='Width of the generated plot', default='640')
    parser.add_argument('-t', '--height', help='Height of the generated plot', default='480')
    parser.add_argument('-p', '--png', help='Filename to store generated histogram as PNG image')

    args = parser.parse_args()
    # print(args.filename, args.buckets, args.outliersOff)

    # Create a random number generator with a fixed seed for reproducibility
    rng = np.random.default_rng(19680801)

    n_bins = int(args.buckets)
    label = args.label
    if args.filename == '-':
        f = sys.stdin
    else:
        f = open(args.filename)

    x = np.array([float(x) for x in f.readlines()])
    if args.outliersOff:
        x = x[~is_outlier(x)]


    # fig, axs = plt.subplots(1, 2, sharey=True, tight_layout=True)
    fig, axs = plt.subplots(1)

    # We can set the number of bins with the *bins* keyword argument.
    axs.hist(x, bins=n_bins, label=label)
    plt.xlabel('Measurements', fontsize=fontsize)
    plt.title(label, fontsize=fontsize)
    axs.tick_params(axis='both', which='major', labelsize=fontsize)
    axs.tick_params(axis='both', which='minor', labelsize=fontsize)

    if args.png:
        fig.savefig(args.png, bbox_inches='tight')
    else:
        plt.show()

if __name__ == "__main__":
    main()
