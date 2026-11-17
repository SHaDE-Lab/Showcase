import argparse
from panomrt.PanoMRT import Entrance

def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Panoramic Mean Radiant Temperature Identifier")
    parser.add_argument('-f', '--file', required=True, nargs='+', help='Path to input data file (*.csv)')
    parser.add_argument('-o', '--output', default='output.csv', help='Path to output file (*.csv)')
    parser.add_argument('-m', '--method', choices=['lindberg', 'open'], default='lindberg',
                        help='Shortwave Radiation method, "lindberg" or "open"')
    parser.add_argument('-i', '--images', required=True, nargs='+', help="Pathway to images for PanoMRT calculation")
    parser.add_argument('-svl', '--sunVisibleLabel', help="Use this argument if you have a sunVisibleLabel and don't need to calculate if the sun is visible.",
        action='store_true')
    parser.add_argument('-n', '--num', type=int, default=0, help="Number of locations to run within the dataset")
    parser.add_argument('--offset', type=int, default=0, help='Offset from start of dataset during run.')
    parser.add_argument('-j', type=int, default=1, help='Number of threads.')
    parser.add_argument('--hours', nargs='+', help="List of the hours (in 24 hour time style) of pictures", type=int, default=[6, 9, 12, 15, 18, 20])
    parser.add_argument('-v', '--verbose', action='store_true', help="Prints information about run")
    parser.add_argument('-d', '--debug', action='store_true', help="Prints debug tools during run")
    # Adding missing arguments from PanoMRT.py
    parser.add_argument('-sv', '--sunVisible', type=int, choices=[-1, 0, 1], default=-1, 
                        help="sunVisible qualifier for single runs")
    parser.add_argument('-p', '--print', action='store_true', 
                        help="Prints final data to console at the end of the run")
    parser.add_argument('--pano', action='store_true', help='Indicate that input images are panoramic and need conversion to cube faces')
    args = parser.parse_args()

    # Process args here instead of in Entrance class
    if args.verbose:
        print("Running:")
        print("Input file: " + str(args.file))
        print("Output file: " + args.output)
        print("Number of threads: " + str(args.j))
        print("Images pathway(s): " + str(args.images))
        if args.offset > 0:
            print("Offset run by: " + str(args.offset))
        if args.num > 0:
            print("Number of runs: " + str(args.num))
        if len(args.hours) > 0:
            print("List of hours used in calculation: " + str(args.hours))
        print("Radiation calculator method: " + args.method)
    
    # Validate arguments
    if args.file is not None and len(args.file) > 1 and (args.num != 0 or args.offset != 0):
        raise RuntimeError("Cannot pass num or offset arguments with more than one datafile. Unable to specify which num or offset goes with which datafile.")
    
    if args.images is not None and args.file is not None:
        if not len(args.images) == 1 and not (len(args.file) == len(args.images)):
            raise RuntimeError("The number of image folders passed must be 1 or equal to the number of datafiles passed.")

    # Pass the parsed arguments to the Entrance object
    e = Entrance(args)
    e.main()

if __name__ == "__main__":
    main()